# Architecture Decision Records

Significant technical and product decisions for tg_sales, recorded so that
future maintainers understand why the application is built the way it is.
Each record lists its status, context, decision, and consequences.

---

## ADR-001: Python 3.13 runtime

**Status:** Accepted (2026-10-25)

**Context.** The application is written in Python and packaged with
PyInstaller into a standalone Windows executable. The development machine has
Python 3.10 and 3.13 available. Python 3.10 is close to end of life and lacks
recent performance and typing improvements.

**Decision.** Target Python **3.13** (64-bit) for development, CI, and release
builds. The interpreter version is pinned in `.python-version`, and the package
metadata will restrict it to `>=3.13,<3.14`.

**Consequences.**
- All dependencies must publish Python 3.13 wheels for Windows x64.
- CI and release builds use the same minor version as local development, so
  results are reproducible.
- End users are unaffected; the interpreter is bundled inside the release.

---

## ADR-002: Local-first, single-device database with offline collaboration

**Status:** Accepted (2026-10-25)

**Context.** Salespeople must be able to work without accounts, cloud
services, subscriptions, or a network connection, and must never lose data when
the application is updated.

**Decision.** Each installation stores its data in a local SQLite database in
the per-user application data directory, separate from the executable.
Collaboration between computers uses explicitly exported and imported change
packages, not a shared server or a shared database file.

**Consequences.**
- Core features work fully offline; replacing the application folder during an
  update never touches user data.
- Merging changes between computers requires idempotent, conflict-aware sync
  packages. Copying SQLite files between computers is not a supported sync
  method.
- Data is protected by the user's Windows account and disk encryption rather
  than by the application itself; this must be documented for users.

---

## ADR-003: No automated outbound communication

**Status:** Accepted (2026-10-25)

**Context.** The application helps salespeople prepare and track outreach to
studios, publishers, and data buyers. Automated sending creates legal,
reputational, and deliverability risk.

**Decision.** tg_sales never sends email, LinkedIn messages, or other outreach
automatically. Users copy prepared messages and send them through their own
approved channels, then log the activity. Activity records claim that a
message was sent only when the user logged it manually.

**Consequences.**
- No email or social-network credentials are ever stored by the application.
- Activity history reflects what salespeople recorded, and the UI and reports
  make that clear.

---

## ADR-004: PyQtGraph charts on PySide6-Essentials

**Status:** Accepted (2026-10-25)

**Context.** Dashboards and reports need responsive, colorful charts (trend,
bar, funnel) that can be rendered to images for snapshots. The candidates were
Qt Charts and PyQtGraph. Qt Charts ships only in the large `PySide6-Addons`
package; PyQtGraph works with the smaller `PySide6-Essentials` package.

**Decision.** Use **PyQtGraph** for charts and depend on
**`PySide6-Essentials`** rather than the full `PySide6` meta-package.

**Consequences.**
- A substantially smaller executable, faster startup, and fewer files for
  antivirus software to scan.
- PyQtGraph handles large data sets efficiently; funnel and stacked charts are
  composed from bar primitives.
- Chart widgets render natively in Qt, so dashboard snapshots can use widget
  rendering instead of screen capture.
- Modules found only in `PySide6-Addons` are unavailable unless this decision
  is revisited.

---

## ADR-005: Hash-pinned dependency lock files with a release-age cooldown

**Status:** Accepted (2026-10-25)

**Context.** Builds must be reproducible, and the dependency supply chain
should be protected against tampered or freshly compromised packages.

**Decision.** `pyproject.toml` declares direct dependencies with compatible
ranges. `scripts/lock_deps.ps1` (pip-tools) generates `requirements.lock` and
`requirements-dev.lock` containing every transitive dependency with exact
versions and SHA-256 hashes. Installs use `pip install --require-hashes`. The
lock script skips package versions uploaded within the last 14 days
(`--uploaded-prior-to`).

**Consequences.**
- Development, CI and release builds install byte-identical dependencies.
- Newly published versions are adopted only after a cooling-off period during
  which compromised releases are usually detected and pulled.
- Lock files are resolved for the supported target, Windows x64 with Python
  3.13; other platforms are not supported build environments.

---

## ADR-006: Data folder override is explicit and outside the program folder

**Status:** Accepted (2026-10-25)

**Context.** Some users may need their data on a specific drive (for example,
a BitLocker-encrypted volume). Storing data next to the executable would be
erased when an update replaces the program folder.

**Decision.** The default data folder is `%LOCALAPPDATA%\TatumGames\tg_sales`.
A custom folder is used only when explicitly requested with `--data-dir` or the
`TG_SALES_DATA_DIR` environment variable. Custom folders must be absolute
paths and are rejected if they are inside the program folder.

**Consequences.**
- Updates never destroy user data, even in custom-folder setups.
- A "portable" layout that stores data next to `tg_sales.exe` is deliberately
  not supported.

---

## ADR-007: Display preferences are device-local JSON, not database data

**Status:** Accepted (2026-10-25)

**Context.** Theme choice and window placement describe how the app looks on
one computer. Sales data in the database is shared between computers through
sync packages.

**Decision.** Store display preferences in `preferences.json` in the data
folder, validated with Pydantic, written atomically, and never synced. The
default theme on first run follows the Windows light/dark setting. A corrupt
file is renamed aside and defaults are used.

**Consequences.**
- Each person's display choices stay on their own computer and never conflict
  during sync.
- Preferences remain readable even if the database is unavailable, so the app
  can always show its window and error messages in the chosen theme.

---

## ADR-008: Fusion style with a token-driven style sheet

**Status:** Accepted (2026-10-25)

**Context.** The native Windows style ignores custom palettes for many
controls, which makes a consistent dark theme impossible.

**Decision.** Use Qt's Fusion style with a palette and style sheet generated
from the theme tokens in `ui/theme.py`. All colors come from tokens; contrast
is verified by automated tests.

**Consequences.**
- Light and dark themes look consistent on Windows 10 and 11.
- Controls follow the tg_sales design rather than the exact Windows look;
  native file dialogs and message boxes are still used.

---

## ADR-009: UUIDv7 text ids and fixed-width UTC text timestamps

**Status:** Accepted (2026-10-25)

**Context.** Records are created independently on several computers and
merged through sync packages, so ids must never collide. Historical metrics
depend on correct, comparable timestamps.

**Decision.** Ids are UUIDv7 (generated locally; Python 3.13 has no built-in)
stored as canonical text. Built-in shared rows use deterministic UUIDv5 ids.
Timestamps are stored as `YYYY-MM-DDTHH:MM:SS.ffffffZ` text through a column
type that rejects naive datetimes.

**Consequences.**
- No coordination is needed between computers; ids are roughly time-ordered,
  which keeps indexes compact.
- Timestamps sort and compare correctly as text in SQL and are readable in sync
  packages and support sessions.
- Text ids use more space than 16-byte binary ids; acceptable at the expected
  data sizes.

---

## ADR-010: Immutable activity ledger with correction events

**Status:** Accepted (2026-10-25)

**Context.** Reports must be able to show the pipeline as it was at any past
moment, and history must survive edits, mistakes and sync between computers.

**Decision.** Every stage change and interaction is an append-only event in
`activities`. SQLite triggers reject updates and deletes, and the ORM refuses
them too. Mistakes are fixed by `correction` events that void or re-time the
original while keeping a copy of its values. Opportunities keep their current
stage for fast queries; the ledger is the source of truth for history.

**Consequences.**
- Past pipeline states are reproducible and auditable.
- Events merge between computers without conflicts (they are only ever
  added).
- Removing personal data from historical events requires a dedicated,
  explicit procedure rather than ordinary deletion.

---

## ADR-011: Back up before every schema upgrade

**Status:** Accepted (2026-10-25)

**Context.** Updating tg_sales may change the database schema. A failed or
faulty upgrade must never cost salespeople their data.

**Decision.** Before migrating an existing database, tg_sales copies it with
SQLite's online backup API into the backups folder and verifies the copy. The
upgrade runs in a single transaction with foreign keys suspended and must pass
a foreign-key check before committing. Databases from newer versions are
refused.

**Consequences.**
- Every upgrade has a verified restore point.
- A failed upgrade leaves the original database unchanged.
- Downgrading the app requires restoring the pre-upgrade backup.

---

## ADR-012: Imports fill gaps, run atomically and are reversible through a change log

**Status:** Accepted (2026-10-25)

**Context.** Salespeople import existing spreadsheets that are messy, may be
imported more than once, and may describe prospects that already exist. A bad
import must never damage curated data and must be easy to take back.

**Decision.**
- An import is planned first (rows interpreted, grouped and matched, nothing
  saved), then previewed by running the full import in a transaction that is
  rolled back, then committed in one transaction. Cancellation or any failure
  saves nothing. Foreign-key checks are deferred to COMMIT for that
  transaction so rows can be inserted in one batch; violations still abort it.
- Imports only fill empty fields and add contacts, games and tags; existing
  values are kept and differences reported.
- Every record an import creates or updates is written to `import_changes`
  with the values it replaced and the source row's fingerprint. Undo uses this
  log in one transaction and keeps records changed after the import.
- Re-imported rows are recognized by fingerprint and skipped. The import id is
  generated when planning, so the same plan cannot be saved twice.
- Only file metadata (name without folder, size, type, SHA-256) is kept, not
  the file or raw rows.

**Consequences.**
- Imports are safe to try and to repeat; the summary shows exact counts.
- Undo is precise without snapshotting the database.
- The change log grows with each import (a few rows per imported record).

---

## ADR-013: Duplicates are suggested from evidence; similar names are never merged automatically

**Status:** Accepted (2026-10-25)

**Context.** Different studios often have similar names ("Moon Owl Games" and
"Moon Owl Game Studio"), while the same studio is written differently across
lists. Wrong merges lose information; missed duplicates clutter the CRM.

**Decision.** The same identifying website domain or contact email is strong
evidence; the same name (ignoring case, punctuation and company forms such as
"Inc" or "GmbH") counts only when no conflicting website exists; similar names
are suggestions only. Shared hosts (webmail, social networks, `itch.io`,
store pages) never identify an organization. When adding a prospect, matches
are shown and the user may open the existing one or create anyway. Imports
match strong evidence automatically and ask the user about everything else.
Similar names are compared only among organizations that share a distinctive
word (common words such as "games" or "studio" are ignored), which keeps
checks fast with 100,000 prospects.

**Consequences.**
- Legitimate similarly named studios can coexist.
- Users decide every uncertain match; nothing is merged silently.

---

## ADR-014: Prospects and contacts are archived, not deleted

**Status:** Accepted (2026-10-25)

**Context.** Salespeople need to hide prospects that are no longer relevant
without losing their history, and mistakes must be easy to reverse.

**Decision.** Organizations and contacts have an `archived_at_utc` column.
Archiving hides them from the default list (a filter shows them again) and is
recorded as a field change in the activity ledger; restoring clears it. The
deletion tombstone (`deleted_at_utc`) remains reserved for real deletion and
for undoing imports.

**Consequences.**
- Archiving is reversible and keeps the timeline.
- Archived prospects still count for duplicate detection.

---

## ADR-015: Stages keep their identity; archiving moves opportunities through the ledger

**Status:** Accepted (2026-10-25)

**Context.** Salespeople must be able to rename, reorder, add and retire
stages without corrupting history, reports or synchronization.

**Decision.** Stages are referenced by immutable ids everywhere (opportunity
rows and stage-change events). Renaming and reordering only change the stage
row. Archiving a stage first moves each of its opportunities with an ordinary
`stage_change` event ("Stage … archived"), so historical counts before the
archive date are unchanged and later counts are correct. Safeguards: at least
one open stage for all lanes must remain; a stage's outcome (open/won/lost/not
a fit) cannot change while it holds opportunities; stages can be limited to a
product lane and opportunities can only enter stages of their lane; moving to
a terminal stage requires a reason code and reopening clears it. Every stage
change is recorded as a `field_change` event.

**Consequences.**
- Reports stay reproducible whatever the stage configuration becomes.
- Removing a stage is always reversible (restore) and never orphans data.

---

## ADR-016: Interactions are logged, never sent; handoffs are drafts

**Status:** Accepted (2026-10-25)

**Context.** tg_sales has no email or messaging integration (ADR-003). Users
must not be misled into believing a message was delivered.

**Decision.** Outreach activities (email, LinkedIn, call, meeting, reply,
demo, data room, proposal, handoff, closed) are recorded as things the
salesperson reports having done, with `logged_manually: true`, and are always
described as "logged". Logging an interaction with a contact moves the
contact's outreach status forward (attempted, then responded), never back.
The technical handoff for data-licensing opportunities produces a copyable
draft for the technical lead (the salesperson enters the recipient; no address
is built in); copying it records a
`technical_handoff` event noting that it was copied for manual sending. The
draft states that no dataset is approved for sale without an authorized
internal review.

**Consequences.**
- History never claims a delivery that tg_sales cannot confirm.
- No personal email addresses are embedded in the application.

---

## ADR-017: KPIs are computed from the ledger on a worker, with a change-aware cache

**Status:** Accepted (2026-10-25)

**Context.** Dashboard numbers must be reproducible for any past period,
reconcile with reports, respect corrections and deletions, and stay
responsive with 100,000 contacts and long histories.

**Decision.** KPIs are calculated in pure Python functions (`domain/kpi.py`)
from column-wise reads of the activity ledger and record timestamps, never
from saved snapshots or current stage values. Periods are local calendar days
converted to UTC per boundary (daylight-saving safe). Calculations run on a
background worker with progress; results are cached per period and filters
and reused while a cheap version token (latest change time and row count of
each table, all indexed) is unchanged and the result is under a minute old.
The KPI dictionary is the specification and a test keeps it aligned with the
implementation.

**Consequences.**
- Numbers for a past period never change unless the underlying history does
  (for example a correction).
- A cold calculation over a very large history takes seconds (about 4–8 s at
  100,000 contacts and 500,000 activities on a typical laptop) but never
  blocks the window; repeated views are instant.
- A pre-aggregated store can be added later without changing definitions.

---

## ADR-018: Steam discovery uses public storefront data, user-started and throttled

**Status:** Accepted (2026-10-25)

**Context.** Salespeople want studios with upcoming or recent releases. The
documented Steam Web API does not offer a catalog of future releases or
developer contacts. The public storefront offers search listings and per-app
details, which `robots.txt` does not disallow, but they are rate limited and
undocumented.

**Decision.** Discovery reads the storefront search, featured lists and app
details only when the user starts it, at one request per 1.5 s with backoff,
stops on 429/401/403 without workarounds, caches details for 24 h and labels
cached data as not current. Users can also add games by pasting Steam links.
Results go to a stored review queue (`discovery_leads`); nothing enters the
CRM without the user choosing Save to Prospects, which checks for duplicates
first. Contacts are only those published on named public pages (the store's
support contact, or the studio's own site when the user asks), always "needs
verification" until the user verifies them. Scores are transparent rule
sums. Sources sit behind a `GameSourceAdapter` protocol with feature flags;
mobile stores stay disabled until a permitted source exists.

**Consequences.**
- Discovery is a curated selection, not a complete market scan; this is stated
  in the UI and documentation.
- If Valve changes or restricts these endpoints, discovery fails gracefully
  and saved results remain available.

---

## ADR-019: Playbook templates keep full-content revisions; copying never sends

**Status:** Accepted (2026-10-26)

**Context.** Outreach wording is shared, edited by several people, and some of
it (figures, incentives) needs business approval. Messages must never be sent
automatically, and a raw `{placeholder}` reaching a prospect is embarrassing.

**Decision.** Each saved edit stores the template's full content as a new
`playbook_revisions` row with author and change summary; restoring writes the
old content as a new revision, so history is never lost. Editing the title or
message of an approved template clears approval. Personalization fills a fixed
set of placeholders from a chosen prospect (editable values) and reports
missing or unknown placeholders; copying unresolved text needs explicit
confirmation. Copy only places text on the clipboard. Example templates are
added on request (identified by `example_key` so they are added once), start
unapproved and carry notes that their figures and incentives need approval.
Outcomes are recorded manually per template. An optimistic revision check
refuses edits based on an outdated version.

**Consequences.**
- History grows with each edit (small text rows).
- Templates sync like any other record; concurrent edits on two computers are
  handled by the sync conflict rules built later.

---

## ADR-020: Reports reuse the dashboard calculation and are rendered with Qt

**Status:** Accepted (2026-10-26)

**Context.** Reports must agree with the dashboard, be shareable as PDF and
CSV, and work offline without extra native dependencies.

**Decision.** A report calls `KpiService.dashboard` for the period and for the
previous period of the same length, then builds plain content objects
(`reports/content.py`). The PDF is a `QTextDocument` printed by `QPdfWriter`
(A4, page numbers, page breaks before major sections); charts are drawn with
`QPainter` onto images at print resolution. The HTML preview is the same HTML
with charts embedded as data URIs; CSVs use the formula-safe writer. Each
report is written to a `.partial` folder and renamed when complete, under a
name containing the UTC epoch milliseconds. Dashboard snapshots are rendered
with `QWidget.grab()` (viewport or whole content), never screen capture, and
recorded in the `snapshots` table; file paths are always checked to stay inside
the app's folders.

**Consequences.**
- No PDF library dependency; layout is limited to what `QTextDocument`
  supports (simple tables, images, page breaks).
- Long lists are shortened in the PDF and complete in the CSVs.
- Snapshot files are local to one computer; their rows record metadata only.

---

## ADR-021: The desktop app becomes a local web app (React + FastAPI + PostgreSQL)

**Status:** Accepted (2026-10-26). Supersedes the PySide6 desktop UI of the
earlier ADRs (the domain, repositories and services are kept).

**Context.** The CRM must be modern, responsive on phones and tablets, ready
for a future hosted team deployment and a mobile app, and still run on one
salesperson's computer without cloud services.

**Decision.** A modular monolith: the existing Python domain and services
behind a FastAPI API (`src/tg_sales/api`), a React + TypeScript single-page
app (`web/`, Vite, Tailwind, shadcn/ui-style Radix components, TanStack
Query, React Hook Form + Zod, Recharts, dnd-kit) served by the same server,
and PostgreSQL as the only database. The Qt UI was removed once the web app
reached parity (verified by browser tests). TypeScript API types and the API
reference are generated from the server's OpenAPI schema.

**Consequences.**
- One code base for desktop browsers, tablets, phones and future hosting; the
  API can serve a React Native/Expo app.
- The browser is the UI: no native window, the app runs at `127.0.0.1`.
- Reports no longer depend on Qt (ReportLab PDF, SVG charts); snapshots are
  rendered by the browser from the page itself.

---

## ADR-022: PostgreSQL runs locally from portable binaries managed by the launcher

**Status:** Accepted (2026-10-26)

**Context.** PostgreSQL must run locally without accounts or subscriptions,
and salespeople must not install or configure a database. The development
computer cannot run Docker (no hardware virtualization), and Docker Desktop
would be a heavy requirement for salespeople anyway.

**Decision.** Ship the official EDB PostgreSQL 18 Windows binaries (zip, no
installer, no administrator rights) in `runtime\postgresql`. The launcher
creates a private cluster per Windows user in the data folder on first start
(random SCRAM passwords, `127.0.0.1` only, loopback-only `pg_hba.conf`),
starts and stops it with `pg_ctl`, and creates the application role and
database. Docker Compose and a Dockerfile are provided for computers that
have Docker and as the base for hosting.

**Consequences.**
- The release ZIP is self-contained (about 95 MB). Backups use the bundled
  `pg_dump`/`pg_restore`, piped through stdin/stdout because these programs
  cannot open file paths outside the Windows code page.
- Tests start throwaway clusters from the same binaries.

---

## ADR-023: Offline sync is built on a trigger-maintained change log with change ancestry

**Status:** Accepted (2026-10-26)

**Context.** Colleagues exchange change files without a server. Exports must
not miss changes, repeated or out-of-order packages must be harmless,
forwarded changes must not loop, and concurrent edits must never be
overwritten silently.

**Decision.** PostgreSQL triggers write a `change_log` row (with a change id)
for every insert/update of a synchronized table. Packages contain each changed
record's values, current change id and full change history. On import, a
record is inserted, skipped (its version is already known), fast-forwarded
(our version is in its history), converged (identical values) or reported as
a field-level conflict that the user resolves; the resolution becomes a new
version whose history contains both sides. Applied changes keep their
original change id (via a session setting read by the trigger). Records whose
references are missing wait in `sync_pending`. Optional AES-256-GCM with a
scrypt key protects package contents.

**Consequences.** Idempotent, loop-free propagation and explicit conflicts,
tested across simulated computers; every synchronized table needs a trigger
and an entry in `SYNCED_TABLES`.

---

## ADR-024: Local security model for a browser-based app

**Status:** Accepted (2026-10-26)

**Context.** A local HTTP server can be attacked by web pages the user visits
(cross-site requests, DNS rebinding), and the CRM has no sign-in yet.

**Decision.** Listen on `127.0.0.1` only and refuse to start on other
addresses until sign-in, roles and HTTPS exist; accept only `127.0.0.1` and
`localhost` host names; require the `X-TG-Sales` header on state-changing
requests (blocked cross-site by CORS preflight) and refuse foreign origins;
strict CSP and security headers; `Cache-Control: no-store` for API responses;
the service worker caches only the app shell. A random secret written to the
lock file lets `stop.bat` shut the server down.

**Consequences.** Safe single-user local operation; hosting requires adding
authentication and replacing the header check with cookie-based CSRF
protection.

---

## ADR-025: Desktop databases are transferred, not opened

**Status:** Accepted (2026-10-26)

**Decision.** The web version never uses SQLite as its database. A transfer
tool copies the desktop SQLite file (online backup API), upgrades the copy to
the last desktop schema, inserts every row into PostgreSQL in one transaction
(ids, timestamps and device ids preserved; identical rows skipped; differing
rows reported, never overwritten; unreadable or orphaned rows reported with
their values), adopts the desktop device identity for a new database, and
verifies every row, activity counts and stage histories afterwards.

**Consequences.** Repeatable, verifiable migration with a written report;
the original file is never modified.
