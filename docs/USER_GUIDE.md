# User guide

TG Sales CRM runs on your computer and opens in your browser. Start it with
**launch.bat**; keep the small tg_sales window open while you work; close that
window (or run **stop.bat**) to quit. Everything is saved immediately.

On a phone or tablet layout, use the menu button (top left) and the bar at
the bottom. On desktop, the sidebar lists every section.

## First start

Enter your name (colleagues see it on what you add) and pick a theme. Add your
company logo on **Resources**.

## Dashboard

- Choose a **period** (last 7 or 30 days, last month, 3, 6 or 12 months,
  previous calendar month/quarter/year, or a custom range); the exact dates
  are shown. Filter by **salesperson** and **product lane**.
- Click any card to see the records behind the number. "Not available" means
  it cannot be calculated (for example a win rate before anything was won or
  lost); 0 means nothing happened.
- Every chart has **Show data table** and a CSV download.
- **Snapshot** saves a PNG of the visible area or the whole dashboard (find it
  on Reports).

## Prospects

- **New prospect** (top bar): name, website, type, location, tags, notes and
  contacts. If it looks like an existing prospect (same website domain,
  contact email or very similar name), tg_sales shows the match; open it or
  choose **Create anyway**.
- Search covers names, websites, contacts (name, email, job title), games and
  tags. Filter by tag and type; **Show archived** includes archived prospects.
- Select several prospects to add or remove a tag, archive, restore or export
  them as CSV.
- A prospect's panel has contacts (with outreach status: you set it, it is
  never guessed), opportunities, games, links, notes and the full timeline.

## Importing a spreadsheet

**Import** (top bar) accepts CSV, Excel (.xlsx) and text files:

1. Choose the file (and the sheet for Excel).
2. Check the columns: tg_sales suggests what each column means, with a
   confidence; change any choice. Say how dates like 03/04/2027 should be read.
3. Review matches: rows are grouped per company; for companies that look like
   existing prospects choose **Create new**, **Add to** the existing one, or
   **Skip** (or decide for all at once). Problems are listed and can be
   exported as CSV.
4. **Preview result** shows exactly what will happen.
5. **Import now** saves everything at once (a backup is made first).

Imports only add missing information; they never overwrite what you have.
**Import history** lets you undo an import (anything edited since is kept).

## Pipeline

- Columns are stages; filter by product lane or by name. Drag a card by its
  handle to another stage (mouse or touch), or use the card's **⋯** menu,
  which also works from the keyboard. Moving to Won, Lost or Not a fit asks for
  a reason.
- **New opportunity**: prospect, product lane, stage, title, salesperson,
  value, next follow-up. A prospect can have one in each lane.
- Open a card to **log activity** (email, LinkedIn, call, meeting, reply,
  demo, data room, proposal…, with an optional earlier date), add notes and
  tasks, edit details, change the stage, or **Mark as mistake** (the entry
  stays visible, crossed out, and stops counting).
- Data licensing opportunities have **Prepare technical handoff**: a copyable
  email for the technical lead. Copying records the handoff; tg_sales never
  sends anything.
- **Manage stages**: rename, reorder, add (optionally for one lane), set the
  outcome, archive (choose where its opportunities go) or restore.
- Follow-ups due today or overdue appear under the bell icon and on the
  Dashboard; overdue is always written out, not just shown in color.

## Discovery

**Find games** checks Steam for games releasing in the next 90 days or
released in the last 150 days (change the windows in the filters or in
Settings). Each result shows the release date and how certain it is,
developers and publishers, genres, a score with its reasons, whether the
studio is already in your CRM, and the business contact if the store or the
official website publishes one. **Review** a game to check the studio website
for a contact, mark a contact as verified, and **Save to Prospects** (as a new
prospect or added to an existing one). **Add Steam links** looks up specific
games. Discovery needs the internet.

## Playbook

Search or filter templates by channel, audience, category, favorites,
approval or archive. Open a template, optionally choose a prospect (and
contact/game) to fill placeholders like `{studio_name}`, check the warnings
(missing values, LinkedIn length) and **Copy message**. Edit, duplicate,
favorite, approve, archive, view **History** (restore any revision) and record
**Outcomes**. Editing an approved template's text removes the approval.
**Add example templates** inserts unapproved examples; check their facts first.

## Reports

Choose a period, salesperson and lane, then **Create report**: a PDF with CSV
data files (and an optional HTML preview), using exactly the dashboard's
numbers. Open, download or delete saved reports. Dashboard snapshots are
listed with a preview.

## Settings & Sync

- **General**: your name, theme, time zone, number format, import and
  discovery preferences, automatic backup schedule and retention.
- **Sync**: share changes with colleagues; see [SYNC.md](SYNC.md).
- **Backups**: **Back up now**, verify, download, delete and **Restore**
  (type RESTORE to confirm; a safety backup is made and the previous data is
  kept until the next restore).
- **Desktop data**: bring in data from the earlier desktop version; see
  [MIGRATION.md](MIGRATION.md).
- **About**: version, sync ID, data folder (open folders), health check and
  privacy information.

## Resources

Bookmarks to web pages (shared with colleagues through sync) and folders on
this computer (opened in Explorer), grouped by category, plus the company logo.

## Install as an app

In Edge or Chrome, use the install icon in the address bar to add TG Sales CRM
to the Start menu or taskbar. It still needs tg_sales running (launch.bat);
the installed app does not keep your CRM data offline.
