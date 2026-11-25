import argparse
import os
import re
import sys
import time
from datetime import date
from pathlib import Path
from urllib.parse import urljoin, urlsplit
from uuid import UUID

import requests
from bs4 import BeautifulSoup
from dotenv import load_dotenv


def source_url(value):
    url = urlsplit(value.strip())
    path = url.path.rstrip("/")
    story = re.fullmatch(r"/(?:[a-z]{2}(?:-[a-zA-Z]{2})?/)?customers/[\w-]+", path)
    release = re.fullmatch(r"/(?:[a-z]{2}(?:-[a-zA-Z]{2})?/)?releases/(\d{4}-\d{2}-\d{2})", path)
    if (
        url.scheme != "https"
        or url.netloc.lower() not in {"notion.com", "www.notion.com"}
        or not (story or release)
    ):
        raise ValueError("Enter an HTTPS Notion customer-story or dated release URL.")
    if release:
        date.fromisoformat(release[1])
    return "https://www.notion.com" + path


def is_release(url):
    return "/releases/" in urlsplit(url).path


def imported_label(url):
    if is_release(url):
        return "Imported release notes"
    return "Imported customer story"


def extract_story(url):
    # Validate each redirect before fetching it.
    target = url
    for _ in range(5):
        response = requests.get(target, timeout=30, allow_redirects=False)
        if not response.is_redirect:
            break
        target = source_url(urljoin(target, response.headers["Location"]))
    else:
        raise ValueError("Too many redirects.")

    response.raise_for_status()
    soup = BeautifulSoup(response.content, "html.parser")
    title = soup.select_one("main h1")
    if is_release(target):
        columns = soup.select('main [class$="_body"] article[class*="_richText"]')
        for column in columns:
            for video in column.select('[class*="_videoContainer"]'):
                video.decompose()
    else:
        columns = soup.select('main [class*="_sectionContent"] [class*="_contentColumn"]')
    if not title or not columns:
        raise ValueError("Could not locate the story title and article sections.")

    parts = []
    for column in columns:
        for element in column.select("h2, h3, p, li, blockquote, figcaption"):
            # A quote or list item may contain paragraphs of its own.
            if any(parent.name in {"li", "blockquote", "figcaption"} for parent in element.parents):
                continue
            content = " ".join(element.get_text(" ", strip=True).split())
            if content:
                parts.append((element.name, content))

    if not any(tag == "p" for tag, _ in parts):
        raise ValueError("The story contained no extractable paragraphs.")
    return title.get_text(" ", strip=True), parts


def rich_text(content, link=None):
    chunks = []
    for start in range(0, len(content), 1900):
        item = {"content": content[start:start + 1900]}
        if link:
            item["link"] = {"url": link}
        chunks.append({"type": "text", "text": item})
    return chunks


def block(kind, content, link=None):
    return {"type": kind, kind: {"rich_text": rich_text(content, link)}}


def story_block(url, title, parts):
    kinds = {
        "h2": "heading_2",
        "h3": "heading_3",
        "li": "bulleted_list_item",
        "blockquote": "quote",
    }
    children = [
        block("heading_2", title),
        block("paragraph", "Original release notes" if is_release(url) else "Original customer story", url),
    ]
    children.extend(block(kinds.get(tag, "paragraph"), text) for tag, text in parts)
    if len(children) > 100:
        raise ValueError("Story exceeds the single-request block limit.")
    toggle = block("toggle", imported_label(url), url)
    toggle["toggle"]["children"] = children
    return toggle


class Notion:
    def __init__(self, token):
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {token}",
            "Notion-Version": "2025-09-03",
        })

    def call(self, method, path, **kwargs):
        for attempt in range(4):
            response = self.session.request(
                method, f"https://api.notion.com/v1/{path}", timeout=30, **kwargs
            )
            if response.status_code != 429 or attempt == 3:
                break
            time.sleep(int(response.headers.get("Retry-After", "1")))
        if not response.ok:
            raise ValueError(f"Notion HTTP {response.status_code}: {response.text[:400]}")
        return response.json()

    def pending_pages(self, data_source_id):
        body = {"filter": {"and": [
            {"property": "Processed", "checkbox": {"equals": False}},
            {"property": "Source URL", "url": {"is_not_empty": True}},
        ]}}
        while True:
            result = self.call("POST", f"data_sources/{data_source_id}/query", json=body)
            yield from result["results"]
            if not result["has_more"]:
                break
            body["start_cursor"] = result["next_cursor"]

    def has_story(self, page_id, url):
        params = {}
        while True:
            result = self.call("GET", f"blocks/{page_id}/children", params=params)
            for item in result["results"]:
                if item["type"] != "toggle":
                    continue
                for text in item["toggle"]["rich_text"]:
                    if text.get("plain_text") == imported_label(url) and text.get("href") == url:
                        return True
            if not result["has_more"]:
                return False
            params["start_cursor"] = result["next_cursor"]

    def import_story(self, page, url):
        page_id = page["id"]
        if not self.has_story(page_id, url):
            title, parts = extract_story(url)
            self.call("PATCH", f"blocks/{page_id}/children", json={
                "children": [story_block(url, title, parts)],
            })
        self.call("PATCH", f"pages/{page_id}", json={
            "properties": {"Processed": {"checkbox": True}},
        })


def main():
    parser = argparse.ArgumentParser(description="Import Notion customer stories and release notes.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--preview", metavar="URL", help="Extract an article and print its text locally.")
    mode.add_argument("--run", action="store_true", help="Import unchecked database rows.")
    parser.add_argument("--releases", action="store_true", help="Use the release notes database with --run.")
    parser.add_argument("--limit", type=int, help="Maximum rows to attempt with --run.")
    args = parser.parse_args()
    if args.limit is not None and (args.limit < 1 or not args.run):
        parser.error("--limit requires --run and a positive integer.")

    if args.releases and not args.run:
        parser.error("--releases requires --run.")

    try:
        if args.preview:
            title, parts = extract_story(source_url(args.preview))
            print(title, *(text for _, text in parts), sep="\n\n")
            return 0

        load_dotenv(Path(__file__).with_name(".env"))
        token = os.getenv("NOTION_TOKEN")
        source_key = "NOTION_RELEASE_DATA_SOURCE_ID" if args.releases else "NOTION_DATA_SOURCE_ID"
        source_id = os.getenv(source_key)
        if not token or not source_id:
            raise ValueError(f"Set NOTION_TOKEN and {source_key} in .env.")
        notion = Notion(token)
        pages = list(notion.pending_pages(str(UUID(source_id))))[:args.limit]
        failures = 0
        for page in pages:
            raw_url = page["properties"]["Source URL"]["url"]
            try:
                url = source_url(raw_url)
                notion.import_story(page, url)
                print(f"Imported: {url}")
            except (requests.RequestException, ValueError) as error:
                failures += 1
                print(f"Failed ({page['id']}): {error}", file=sys.stderr)
        print(f"{len(pages) - failures} imported, {failures} failed.")
        return int(failures > 0)
    except (requests.RequestException, ValueError) as error:
        print(error, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
