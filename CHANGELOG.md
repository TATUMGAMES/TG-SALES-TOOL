# Changelog

All notable changes to TG Sales CRM. Versions follow semantic versioning.

## [Unreleased]

### Added
- **Configurable sales lanes** (Settings › Sales lanes): create, rename,
  describe, color, reorder, archive and restore lanes; move every record of a
  lane to another lane; delete lanes no record uses; add preset sets. Lanes
  drive the pipeline tabs, opportunity forms, stage manager, dashboard and
  report filters and the API. The technical-review handoff is now a lane
  setting.
- **Custom fields** for prospects and contacts (text, number, date, URL,
  yes/no): Settings › Custom fields, on records, in imports (including
  "+ Create custom field…" while mapping columns) and in prospect CSV exports.
- **Review date** and **qualification source URL** on prospects, recognized
  in imports (*Reviewed On*, *Source URL*…), editable, shown on the prospect
  (the URL as a safe link) and exported. URLs are kept exactly, including the
  query and fragment.
- Import mapping: grouped field list, per-column warnings for duplicate
  choices and example values that do not fit the field, an explicit
  **Replace existing values** option (undo restores replaced values), and a
  summary of rows imported, skipped and failed.
- **Branding** (Settings › Branding): company name, logo, compact logo,
  favicon and accent color, with Restore defaults. Safe SVG logos are
  accepted.
- `LICENSE` (Apache 2.0), `NOTICE`, `TRADEMARKS.md`, `CONTRIBUTING.md`,
  license headers in source files (`scripts/license_headers.py`, checked in
  CI) and license information on the About page.

### Changed
- **License:** the software is now open source under the Apache License,
  Version 2.0 (previously proprietary).
- Database revision `0002`. Upgrading keeps the original lanes (Data
  licensing, Publisher partnership, MIKROS Marketing) and every record; new
  installations start with General Sales, Partnerships and Other.
- The company logo moved from Resources to Settings › Branding (the same file
  is used, so existing logos keep working).
- The README was rewritten for new users and developers.

### Fixed
- Editing a contact no longer drops its other social links, provenance or
  source URL.

## [0.1.0] - unreleased

First release, as a local web application.

### Added
- Web app (React + TypeScript) served by a FastAPI server on `127.0.0.1`,
  with light and dark themes, responsive layouts for desktop, tablet and
  phone, and installable PWA support.
- PostgreSQL 18 database, started privately per Windows user by `launch.bat`
  from bundled portable binaries; `stop.bat` stops everything.
- Dashboard with period, salesperson and lane filters, drill-down, charts with
  data tables and CSV, and browser-rendered PNG snapshots.
- Prospects and contacts with duplicate warnings, bulk actions and safe CSV
  export; spreadsheet import wizard with preview, decisions, history and undo.
- Pipeline with custom stages, drag and drop (mouse, touch, keyboard) and a
  menu alternative, outreach logging, tasks, follow-up reminders, won/lost
  reasons and technical-review handoffs.
- Steam game discovery with scoring, provenance and saving to the CRM.
- Playbook of outreach templates with placeholders, revisions, approval and
  outcomes.
- PDF/CSV/HTML reports (ReportLab), report metadata in the database.
- Offline collaboration packages with field-level conflict resolution,
  duplicate flagging and optional AES-256-GCM encryption.
- Settings, Resources (bookmarks, company logo), verified backups with
  retention, schedule and safe restore, health check.
- Transfer of data from the earlier desktop (SQLite) version, with
  verification and a report.
- Windows release ZIP (`tg_sales.exe`, PostgreSQL, web app), Docker Compose
  files, GitHub Actions CI and draft-release workflow.

### Security
- Loopback-only server and database, host/origin checks, anti-forgery header,
  strict security headers, validated uploads, redacted logs, hash-pinned
  dependencies.
