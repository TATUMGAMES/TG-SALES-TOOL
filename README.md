# TG Sales CRM

**A sales CRM you run yourself and set up for your own business.** Free,
open source (Apache 2.0), and private by default.

| Light | Dark (phone) |
|-------|--------------|
| ![Dashboard](docs/screenshots/web_dashboard_desktop_light.png) | ![Prospects on a phone](docs/screenshots/web_prospects_mobile_dark.png) |

## Contents

1. [What is TG Sales CRM?](#1-what-is-tg-sales-crm)
2. [Key features](#2-key-features)
3. [Getting started](#3-getting-started)
4. [First-time setup](#4-first-time-setup)
5. [How to use the CRM](#5-how-to-use-the-crm)
6. [Importing spreadsheets](#6-importing-spreadsheets)
7. [Customizing your company branding](#7-customizing-your-company-branding)
8. [Managing sales lanes](#8-managing-sales-lanes)
9. [Data storage and privacy](#9-data-storage-and-privacy)
10. [Configuration and developer guide](#10-configuration-and-developer-guide)
11. [Open-source license](#11-open-source-license)
12. [Contributing](#12-contributing)
13. [Troubleshooting](#13-troubleshooting)

---

## 1. What is TG Sales CRM?

TG Sales CRM helps a sales team keep track of the companies they sell to,
the people they talk to, and the deals in progress. It runs in your web
browser, but the program and your data stay on your own computer (or your own
server). You don't need an account, a subscription or a cloud service.

It was built by [Tatum Games, LLC](https://github.com/TATUMGAMES) for selling
to game studios and publishers. It can be customized for other kinds of
business: you choose your company name and logo, your **sales lanes** (the
kinds of deals you do, such as "Consulting" or "Software licensing"), and
extra **custom fields** for information your business tracks. None of this
requires changing code.

## 2. Key features

- **Prospects and contacts.** Each company can have several contacts, notes,
  tags, links, a review date, a qualification source link, custom fields and
  a full activity timeline. It warns you about likely duplicates, and you can
  tag, archive or export many prospects at once.
- **Spreadsheet import.** Imports CSV, Excel (`.xlsx`) and text files. It
  suggests a field for each column, lets you create custom fields while
  mapping, and shows a preview. You review possible duplicates before
  anything is saved. It also keeps an import history, and you can undo any
  import.
- **Pipeline.** Opportunities move through stages you configure, on a
  drag-and-drop board (mouse, touch or keyboard). It records won/lost reasons
  and lets you log outreach (email, LinkedIn, calls, meetings…), add tasks and
  track follow-up reminders.
- **Configurable sales lanes.** You define the categories of deals. Lanes
  appear in the pipeline, dashboard, reports and filters.
- **Dashboard and reports.** Shows KPIs for any period, by salesperson and
  lane, built from the recorded history. You can drill down into the
  numbers, and see charts with data tables and CSV. It produces PDF reports
  with CSV data, and PNG snapshots.
- **Playbook.** Reusable outreach templates with placeholders, previews,
  revision history, approval and recorded outcomes.
- **Game discovery** (game-industry feature). Finds upcoming and recent
  Steam releases and their studios' public business contacts, with a scoring
  you can see, and saves them to the CRM.
- **Collaboration without a server.** Colleagues exchange encrypted change
  files. Conflicts are shown field by field and never silently overwritten.
- **Branding, backups and more.** Your company name, logo, browser icon and
  accent color. Automatic, verified database backups with safe restore.
  Light and dark themes. Works on phones and tablets and can be installed as
  an app.

## 3. Getting started

TG Sales CRM is a web application: a small server program (Python), a
private database (PostgreSQL) and a web page (React). The Windows launcher
starts all of it for you.

### Option A: Windows, from the release ZIP (for salespeople)

When a release is published on the
[Releases page](https://github.com/TATUMGAMES/TG-SALES-TOOL/releases):

1. Download `tg_sales_windows_x64_v<version>.zip` (not the "Source code"
   archives).
2. Right-click the ZIP › **Extract All…** into a folder you can write to, for
   example `Documents\TG Sales CRM`.
3. Double-click **`launch.bat`**. A small *TG Sales CRM* window opens, and
   then your browser opens the app.

The ZIP includes everything, PostgreSQL too. Windows SmartScreen may warn
that the program is not signed. Compare the ZIP's SHA-256 with
`SHA256SUMS.txt` from the release, then choose **More info › Run anyway**.

### Option B: Windows, from the source code (for developers and testers)

**Required software:**

| Software | Version | Where to get it |
|----------|---------|-----------------|
| Windows | 10 or 11 (64-bit) | |
| Python | 3.13 | <https://www.python.org/downloads/> (tick "Add python.exe to PATH") |
| Node.js | 22 or newer | <https://nodejs.org> |
| Git | any recent | <https://git-scm.com> |

**Steps** (in a Command Prompt or PowerShell window):

1. Clone the repository:

   ```bat
   git clone https://github.com/TATUMGAMES/TG-SALES-TOOL.git
   cd TG-SALES-TOOL
   ```

2. Install everything (run this once). `setup.bat` creates the Python
   environment, installs the hash-checked dependencies, downloads and
   verifies a portable PostgreSQL into `runtime\postgresql`, and builds the
   web app. It needs internet access.

   ```bat
   setup.bat
   ```

3. Start the app:

   ```bat
   launch.bat
   ```

**Database and migrations happen automatically.** On the first start,
`launch.bat` creates a private PostgreSQL database for your Windows account.
On every start it brings the database up to the latest version. A backup is
made before any upgrade, and a failed upgrade changes nothing. You don't
configure a database or run migrations by hand.

**Environment variables are optional** for the Windows launcher; see
[section 10](#10-configuration-and-developer-guide).

### Opening, stopping and restarting

- **Open:** the browser opens automatically at <http://127.0.0.1:8765>. If it
  doesn't, type that address yourself.
- **Stop:** close the *TG Sales CRM* window, or double-click **`stop.bat`**.
- **Restart:** run `stop.bat`, then `launch.bat`.
- Everything you do is saved immediately; there is no "Save file" step.

### Option C: Docker (optional)

For running on a server or on Linux/macOS. Install
[Docker Desktop](https://www.docker.com/products/docker-desktop/) or Docker
Engine with Compose, then:

```bash
cp deploy/.env.example deploy/.env      # Windows: copy deploy\.env.example deploy\.env
# edit deploy/.env and set TG_SALES_DB_PASSWORD to a long random password
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
# open http://127.0.0.1:8765
docker compose -f deploy/docker-compose.yml --env-file deploy/.env down   # stop
```

The database is in the `pgdata` volume. Backups, branding images and other
files are in the `appdata` volume (`/data`). Both survive `down`/`up` and
rebuilds. Both ports are published on `127.0.0.1` only. The Docker files have
not yet been run end to end by the maintainers; see
[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md).

## 4. First-time setup

1. **Your name.** The welcome screen asks for your name. Colleagues see it on
   what you add.
2. **Company name, logo and colors.** Open **Settings & Sync › Branding**.
   Enter your company name and upload a logo, and optionally a compact logo,
   a browser-tab icon and an accent color. See
   [section 7](#7-customizing-your-company-branding).
3. **Sales lanes.** Open **Settings & Sync › Sales lanes**. A new
   installation starts with *General Sales*, *Partnerships* and *Other*.
   Rename them, add your own, or add the *Tatum Games* preset. See
   [section 8](#8-managing-sales-lanes).
4. **Custom fields (optional).** Open **Settings & Sync › Custom fields** to
   add fields such as "Account tier". You can also create them later while
   importing.
5. **Your first prospect.** Click **New prospect** at the top. Enter the
   company name (and optionally its website, contacts, review date and
   qualification source), then **Create prospect**.
6. **Or import an existing spreadsheet.** Click **Import** at the top. See
   [section 6](#6-importing-spreadsheets).

## 5. How to use the CRM

1. **Open the dashboard.** It shows what happened in the chosen period. Pick a
   period, salesperson or sales lane; click any number to see the records
   behind it.
2. **Add or import prospects.** Use **New prospect** for one company, or
   **Import** for a spreadsheet.
3. **Review the spreadsheet's column mapping.** Check what each column will
   be saved as. Create a custom field for anything not on the list.
4. **Confirm the imported data.** Decide what to do with likely duplicates,
   look at the preview, then choose **Import now**.
5. **Organize records into lanes.** On the **Pipeline** page, choose **New
   opportunity**, then pick the prospect, the sales lane and the stage. A
   prospect can have one opportunity per lane.
6. **Update prospect information.** Open a prospect from **Prospects** and use
   the pencil button to edit details, the review date, the qualification
   source and custom fields. Add contacts, games and notes in its panel.
7. **Track activities and follow-ups.** Open an opportunity to log emails,
   calls, meetings and other activity, add tasks, and set the next follow-up
   date. Due and overdue follow-ups appear under the bell icon.
8. **Review pipeline progress.** On the **Pipeline** board, drag cards between
   stages (or use a card's **⋯** menu). Filter by lane with the tabs.
9. **Use reports and exports.** **Reports** creates a PDF with CSV data for any
   period. On **Prospects**, select records and choose **Export CSV**. Custom
   fields are included as extra columns.

More detail: [docs/USER_GUIDE.md](docs/USER_GUIDE.md).

## 6. Importing spreadsheets

**Supported files:** CSV (comma, semicolon, tab or `|`), Excel `.xlsx` (you
choose the sheet), and text files. The limits are 50 MB, 100,000 rows and 200
columns. Macro-enabled and old `.xls` files are refused for safety, and
formulas are never calculated.

**How column mapping works:** each column gets a suggested field based on its
name, for example *Company* → Company name, *Website* → Website, *Email
Address* → Contact email, *Notes* → Company notes, *Reviewed On* → Review
date. Suggestions are only a starting point: you can change any of them or
choose **Don't import**. A column chosen twice is marked in red. When example
values don't look like the chosen type (a date, a web address, a number,
yes/no), the column shows a warning.

**Review Date:** a column named *Reviewed On*, *Review Date*, *Last
Reviewed*, *Date Reviewed* or *Reviewed Date* is mapped to **Review date**,
meaning when the prospect was last reviewed or qualified. Values like
`2026-03-14`, `14/03/2026` or `March 14, 2026` are accepted. Ambiguous dates
like `04/03/2026` are reported and left empty unless you choose the date
order.

**Qualification Source URL:** a column named *Qualification Source URL*,
*Source URL*, *Research URL*, *Reference URL* or *Qualification Link* is
mapped to **Qualification source URL**: the page where you found or
qualified the prospect. It is saved exactly as written, including
everything after `?` and `#`, for example
`https://research.example/lists?segment=indie&page=3#entry-12`. Only `http`
and `https` addresses are accepted. The CRM never opens them itself; on the
prospect it's a link that opens in a new tab. A column named just *Source*
isn't mapped there, because it usually means a lead source such as
"Referral".

**Creating custom fields:** in a column's list choose **+ Create custom
field…**. Give the field a name (the column name is filled in), a type
(Text, Number, Date, Web address or Yes/no) and whether it belongs to
prospects or contacts. The field is then used for that column and offered
in every later import. For example, a column *Account Tier* with values
*Gold*, *Silver* becomes a text field "Account Tier".

**Previewing:** **Check rows** lists every problem by row and column. You
can export the list as CSV. **Preview result** then does a trial run that
saves nothing and shows exactly how many rows will be imported, skipped or
fail.

**Duplicate records:** rows matching a prospect you already have (same
website domain or contact email, or the same name) are added to it.
Uncertain matches wait for your decision: **Create new**, **Add to** the
existing prospect, or **Skip**. By default an import only fills empty fields
and keeps what you already have. To let the file win, switch on **Replace
existing values** before checking rows; names, notes, tags and outreach
status are never replaced.

**Correcting import errors:** the result shows **rows imported**, **rows
skipped** and **rows failed**, with the reason for each problem. Fix the
cells in your spreadsheet and import it again: rows that were already
imported are recognized and skipped. Or edit the prospect directly. Any
import can be undone from **Import history**.

Full reference: [docs/IMPORTING.md](docs/IMPORTING.md).

## 7. Customizing your company branding

Open **Settings & Sync › Branding**:

| What | How |
|------|-----|
| **Company name** | Type it and choose **Save**. It appears under "TG Sales CRM" in the sidebar and menu, and in the browser tab title. Leave it empty for the default ("Tatum Games"). |
| **Logo** | **Choose image…** under *Company logo*. Shown in the sidebar and menu. |
| **Compact logo** (optional) | Used in small spaces such as the phone header. When not set, the main logo is used. |
| **Favicon** (optional) | The icon in the browser tab, saved as 64 × 64. |
| **Accent color** (optional) | Pick a color or type `#rrggbb`; buttons, links and the selected menu item use it. Text on it is made black or white automatically for readability. |
| **Restore default branding** | Removes your images and resets the name and color. Your CRM records are not affected. |

**Image types:** PNG, JPEG, WebP or BMP up to 5 MB and 4096 × 4096 pixels.
These are checked, resized and saved as a clean PNG copy. Simple SVG files
up to 512 KB are also accepted. SVGs that contain scripts, event handlers,
embedded web content or links to other files or sites are refused.

**Where it's stored:** the images go in the `assets` folder of your data
folder (`%LOCALAPPDATA%\TatumGames\tg_sales\assets` on Windows, `/data/assets`
with Docker), and the settings go in the database. Branding therefore
survives restarts, updates and rebuilds of the web app. Database backups
don't include the image files, so copy the `assets` folder if you want a
copy of your logo.

**The project's `assets` folder isn't read by the app.** Copying a logo into
the `assets` folder of the source code (next to this README) does nothing.
Upload your logo in Settings › Branding instead. That one place works the
same way for the Windows app, source checkouts and Docker.

Changing the branding never changes the software's copyright or license
notices (see [section 11](#11-open-source-license)).

## 8. Managing sales lanes

A **sales lane** is a category of deals, such as "Enterprise Sales",
"Consulting" or "Sponsorships". Lanes are not **stages**. Stages ("Contacted",
"Negotiation", "Won") are steps every deal goes through, and they are managed
with **Manage stages** on the Pipeline page. A stage can also be limited to
one lane.

Open **Settings & Sync › Sales lanes**:

- **Create a lane:** **Add lane**. Enter a name, an optional description and a
  color. Turn on *technical-review handoffs* if the lane's deals need a
  handoff summary for a technical reviewer.
- **Rename a lane:** **Edit**. Every opportunity and its history stays in the
  lane: records point to the lane's permanent identifier, not its name.
- **Reorder lanes:** use the up and down arrows. The order is used in the
  pipeline tabs and filters.
- **Archive a lane:** **Archive**. New opportunities can't use it, but its
  opportunities, stages and history stay exactly as they are and still show
  in the pipeline, dashboard and reports. **Restore** brings it back.
- **Move records between lanes:** **Move records** moves every opportunity in
  the lane, and every stage limited to it, to the lane you choose. A backup
  is made first, and each move is recorded on the opportunity's timeline.
- **Safely remove unused lanes:** **Delete** is offered only for a lane that
  no opportunity or stage uses, and asks for confirmation. A lane with
  records can't be deleted: move its records first, or archive it instead.
- **Presets:** *Add a set of lanes* adds the lanes of a preset you don't
  have yet, for example the original Tatum Games lanes (Data licensing,
  Publisher partnership, MIKROS Marketing). Existing lanes are not changed.

**Upgrading an existing installation** keeps its original lanes and all
records. New installations start with General Sales, Partnerships and Other.

## 9. Data storage and privacy

- **Where your data is:** in a private PostgreSQL database and data folder on
  your computer: `%LOCALAPPDATA%\TatumGames\tg_sales` on Windows (or the
  folder given with `--data-dir` / `TG_SALES_DATA_DIR`). With Docker, it's
  in the Docker volumes. Updating the program never touches this folder.
- **Data stays local by default:** the app and its database only accept
  connections from the same computer. There is no telemetry, no analytics,
  and no automatic emails.
- **When it contacts other services:** only when you use **Game discovery**
  (public Steam store pages and studios' official websites), or when you
  export a sync file or download something yourself. Links you save, such as
  qualification sources, are never fetched by the server.
- **Backups:** automatic backups run every 24 hours by default. You can also
  choose **Back up now** in **Settings & Sync › Backups**. Backups are
  verified and kept in the `backups` folder of the data folder. They contain
  the database; copy the data folder's `assets` folder too if you want your
  branding images.
- **Restoring:** in **Settings & Sync › Backups**, choose **Restore** on a
  backup and type RESTORE to confirm. A safety backup of the current data is
  made first.
- **Before exposing it to the internet:** don't. The app has no sign-in
  yet, so anyone who can reach it can read and change everything. It refuses
  to listen on a network address unless explicitly configured. Even then,
  it must not be used without authentication and HTTPS, which are not built
  in yet. Anyone who can sign in to your Windows account can read the data,
  so use disk encryption (for example BitLocker) on laptops.

Details: [docs/SECURITY.md](docs/SECURITY.md).

## 10. Configuration and developer guide

**Architecture:** FastAPI (Python 3.13) serves the JSON API under `/api` and
the built React + TypeScript web app (Vite, Tailwind CSS) from the same
address. Data is in PostgreSQL 18 through SQLAlchemy 2, with Alembic
migrations. The Windows launcher runs a private portable PostgreSQL per user.

```
src/tg_sales/   domain/ (pure rules) · services/ (use cases) · repositories/ · db/ (models,
                migrations_pg/) · api/ (FastAPI routers) · reports/ · sync/ · launcher/
web/            React app (src/features per screen, src/lib hooks and API client), e2e tests
tests/          unit/, integration/ (real PostgreSQL), api/ (HTTP)
deploy/         Dockerfile, docker-compose.yml, .env.example
scripts/        setup, quality gate, Windows build, generators
```

**Environment variables** (all optional for `launch.bat`; prefix `TG_SALES_`):

| Variable | Purpose |
|----------|---------|
| `TG_SALES_DATA_DIR` | Data folder (default `%LOCALAPPDATA%\TatumGames\tg_sales`) |
| `TG_SALES_DATABASE_URL` | PostgreSQL URL (set by the launcher; required for Docker/hosting) |
| `TG_SALES_ADMIN_DATABASE_URL` | Administrator URL, needed only for restoring backups |
| `TG_SALES_HOST` / `TG_SALES_PORT` | Listen address (default `127.0.0.1:8765`) |
| `TG_SALES_ENVIRONMENT` | `production` (default), `development` (API docs at `/api/docs`) or `test` |
| `TG_SALES_STATIC_DIR` | The built web app (`web/dist`) |
| `TG_SALES_PG_BIN` | Folder with PostgreSQL programs (`pg_ctl`, `pg_dump`) |
| `TG_SALES_PDF_FONT` | TrueType font file for PDF reports |
| `TG_SALES_LOG_LEVEL`, `TG_SALES_ALLOWED_ORIGINS`, `TG_SALES_ALLOW_REMOTE` | Advanced; see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |

**Migrations:** applied automatically at start-up, after a backup. To create
one: `.venv\Scripts\python scripts\new_migration.py "description" 0003` (the
next revision number). See
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md#database-migrations) and the
documented schema in [docs/DATA_MODEL.md](docs/DATA_MODEL.md).

**Development with hot reload:**

```powershell
.venv\Scripts\python -m pip install --require-hashes -r requirements-dev.lock
.venv\Scripts\python -m tg_sales.launcher start --no-browser --data-dir "$PWD\runtime\dev-data"
cd web; npm run dev        # http://127.0.0.1:5173
```

**Tests and the build:**

```powershell
powershell -File scripts\check.ps1          # format, lint, types, API types, headers, tests, web build
powershell -File scripts\check.ps1 -E2E     # plus browser tests (Playwright)
.venv\Scripts\python -m pytest              # backend tests only (starts a throwaway PostgreSQL)
cd web; npm test; npm run build             # web unit tests and production build
powershell -File scripts\build_windows.ps1  # Windows release folder and ZIP
```

| Topic | Document |
|-------|----------|
| Architecture and project structure | [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) |
| Development, migrations, scripts | [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) |
| Testing | [docs/TESTING.md](docs/TESTING.md) |
| HTTP API (generated) | [docs/API.md](docs/API.md) |
| Database schema | [docs/DATA_MODEL.md](docs/DATA_MODEL.md) |
| Installation, Docker, hosting | [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) |
| Using the app | [docs/USER_GUIDE.md](docs/USER_GUIDE.md) |
| Importing | [docs/IMPORTING.md](docs/IMPORTING.md) |
| Collaboration (sync) | [docs/SYNC.md](docs/SYNC.md) |
| Reports, KPIs | [docs/REPORTS.md](docs/REPORTS.md), [docs/KPI_DICTIONARY.md](docs/KPI_DICTIONARY.md) |
| Moving from the desktop version | [docs/MIGRATION.md](docs/MIGRATION.md) |
| Security and privacy | [docs/SECURITY.md](docs/SECURITY.md) |
| Troubleshooting | [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) |
| Changes | [CHANGELOG.md](CHANGELOG.md) |

## 11. Open-source license

TG Sales CRM is licensed under the
[Apache License, Version 2.0](LICENSE). In plain language (the license text
is what counts):

- **You may** use the software for any purpose (including commercially),
  copy it, modify it and share your modified versions, free of charge.
- **You must** include a copy of the license and the [NOTICE](NOTICE) file
  when you redistribute it, keep the existing copyright notices, and mark
  files you changed.
- **There is no warranty:** the software is provided "as is".
- **Patents:** contributors grant you a license to any of their patents the
  software needs.

**Copyright:** Tatum Games, LLC keeps the copyright in its original
contributions (Copyright 2013-present Tatum Games, LLC). Contributors keep
the copyright in theirs and license them under the same terms.

**Trademarks and branding:** the license doesn't give you rights to the
Tatum Games names, logos or app icon (see [TRADEMARKS.md](TRADEMARKS.md)).
You can and should put your own company branding on your installation in
Settings › Branding. Tatum Games doesn't own your branding or your CRM data.

## 12. Contributing

Bug reports, ideas and pull requests are welcome. In short:

- **Report a bug:** open an issue with the steps to reproduce, what you
  expected and what happened, and your version (Settings › About). Never
  attach real customer data.
- **Suggest an improvement:** open an issue describing the problem it solves.
- **Submit a pull request:** work on a branch, add or update tests and
  documentation, and run `powershell -File scripts\check.ps1 -E2E`.
- **Coding conventions:** follow the existing structure (pure rules in
  `domain/`, use cases in `services/`, one router per feature), keep types
  strict, and add the license header to new files
  (`scripts\license_headers.py`).

See [CONTRIBUTING.md](CONTRIBUTING.md).

**Privacy:** this repository is public. Never commit real prospect lists,
contact details, databases, backups, sync packages, credentials or internal
documents. `.gitignore` excludes the usual ones, but check `git status`
anyway.

## 13. Troubleshooting

| Problem | What to try |
|---------|-------------|
| The application does not launch | From source, run `setup.bat` first. With the release, extract the whole ZIP again. Read the message in the TG Sales CRM window; the log is at `%LOCALAPPDATA%\TatumGames\tg_sales\logs\tg_sales.log`. |
| The browser page does not load | Check that the TG Sales CRM window is still open, then open <http://127.0.0.1:8765> yourself. If it says "already running", run `stop.bat` and `launch.bat`. |
| The database connection fails | Another program may use port 54329: close it or restart Windows. "Created by a newer version" means you need the latest release. With Docker, check `TG_SALES_DB_PASSWORD` in `deploy/.env` and that the `db` container is healthy. |
| The logo does not appear | Upload it in Settings › Branding (not in the project's `assets` folder), then reload the page. The upload message explains a refused image. |
| A spreadsheet import fails | Save it as `.xlsx` or CSV (UTF-8) with one header row. Read the row problems on the import screen or export them as CSV. |
| A field is missing from the import dropdown | Choose **+ Create custom field…** in that column's list, or restore an archived field in Settings › Custom fields. |
| A new lane is not visible | Make sure it is not archived (Settings › Sales lanes) and reload the page. |

More: [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md).
