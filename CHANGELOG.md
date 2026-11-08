# Changelog

All notable changes to TG Sales CRM. Versions follow semantic versioning.

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
