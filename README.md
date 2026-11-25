# Notion Customer Story and Release Notes Importer

Import public Notion customer stories and dated release notes into the page body of existing database rows. The script copies article text and headings, with a link to the original story. It adds a toggle to the page, so you can use the space around it for your own notes.

## 1. Make the database

Create a private full-page Notion database named **Notion Customer Stories** with these properties.

| Property | Type |
| --- | --- |
| Name | Title |
| Source URL | URL |
| Processed | Checkbox |

Add a row named **Vercel** and paste https://www.notion.com/customers/vercel into **Source URL**. Leave **Processed** unchecked. The next story to try is https://www.notion.com/customers/ramp.

Use your existing personal internal integration if it has Read, Insert, and Update content capabilities, or create one at https://www.notion.so/my-integrations. In the database menu, add that integration under **Connections**. Get the **data source ID** from the original database's **Manage data sources** menu by opening the source's menu and selecting **Copy data source ID**. The database ID and view ID are different identifiers. See https://developers.notion.com/docs/upgrade-guide-2025-09-03 for details.

## 2. Set up Python in VS Code

Open this folder in VS Code and run the following in a PowerShell terminal with Python 3.10 or later.

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
Copy-Item .env.example .env
code .env
```

Paste your internal integration token in `NOTION_TOKEN` and the copied data source ID in `NOTION_DATA_SOURCE_ID`. Keep `.env` local.

## 3. Preview and import

```powershell
.\.venv\Scripts\python.exe import_stories.py --preview https://www.notion.com/customers/vercel
.\.venv\Scripts\python.exe import_stories.py --run --limit 1
```

The preview reads the public website and prints the extracted text. The second command looks for a row with a URL and an unchecked **Processed** box. Open that row in Notion to verify the article and its source link, then run the command again to check that the row is skipped. Add more URLs and use `--run` to import all pending rows.

Run one importer at a time. If a row fails, it stays unchecked and the terminal prints the error. If the article saved but the checkbox update failed, rerunning detects the existing article for that URL and completes the checkbox update. If you want to start over on a row, remove its imported toggle and uncheck **Processed**.

## Code walkthrough

- Start at `main()` to see argument parsing, environment variables, and per-row error handling.
- Follow `extract_story()` to see how Beautiful Soup selects story sections and skips duplicate text nested in quotes and list items.
- Follow the `Notion` class to see how requests, database filters, pagination, and writing content fit together.

The extractor targets Notion's public customer-story layout. Stories that use a different layout or exceed the single-request block limit stay unchecked for inspection.

## Import release notes

Create a separate **Notion Release Notes** database with one row per release. Add **Name** (title), **Source URL** (URL), and **Processed** (checkbox). Add **Release Date** (date) if you want to sort releases by date. Copy the new database’s data source ID.

Connect the same internal integration under **Connections** on the release notes database. Add this line to the existing local `.env` while keeping your current token and customer-story ID.

```dotenv
NOTION_RELEASE_DATA_SOURCE_ID=your_release_notes_data_source_id
```

```powershell
.\.venv\Scripts\python.exe import_stories.py --preview https://www.notion.com/releases/2026-10-19
.\.venv\Scripts\python.exe import_stories.py --run --releases --limit 1
.\.venv\Scripts\python.exe import_stories.py --run --releases
```

Add more dated URLs from https://www.notion.com/releases as unchecked rows. Each import includes the release title, text, and a link to the source. Use the plain `--run` command for the customer-story database.
