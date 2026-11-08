# tg_sales — Product Requirements and Traceability

This document is the requirements baseline for **tg_sales**, the Tatum Games
local-first web CRM and game-market sales intelligence application. Every
requirement has a stable ID. The traceability matrix at the end maps each
requirement to its implementation module, automated tests, and UI location,
and is updated as features are delivered.

## 1. Mission

tg_sales is a polished, local-first web application (React front end,
FastAPI server, PostgreSQL database) that helps Tatum Games salespeople find,
track, and convert business opportunities. On Windows it runs entirely on the
salesperson's computer from a release ZIP started with `launch.bat`; the
browser is the user interface. Salespeople never install Python, PostgreSQL or
run scripts. The architecture is ready for a future centrally hosted
deployment and a mobile app. The complete source code is available in the
public GitHub repository.

### Product priorities

The application supports three sales lanes, in priority order:

1. **Data licensing** — MIKROS Analytics and historical operational data.
2. **Publisher partnerships** — collaboration with video-game publishers.
3. **MIKROS Marketing** — sales to game developers and studios across platforms.

## 2. Core requirements

These requirements apply to every feature.

| ID | Requirement |
|----|-------------|
| CORE-01 | **Offline operation.** CRM, dashboards, reporting, importing, playbooks, snapshots, and sync work with no network connection. Network access is used only for game discovery and for optionally opening URLs in the user's browser. |
| CORE-02 | **No external dependencies for core use.** No account, cloud database, API key, subscription, telemetry, or paid AI service is required for core functionality. |
| CORE-03 | **Durable local persistence.** Every important operation is saved to a PostgreSQL database running privately on the user's computer, stored outside the application folder. Closing and restarting the app preserves all data. |
| CORE-04 | **Fast, simple usability.** The interface is simple and attractive; a new user can add a lead and log an outreach activity within one minute. |
| CORE-05 | **Engineering completeness.** The product ships with end-to-end tests, documentation, backups, deterministic sync, and an automated release workflow. |
| CORE-06 | **No placeholders or fake data.** Every visible button performs a real action. No data is presented as live unless it is; optional demo content is explicitly labeled. |
| CORE-07 | **Responsible data handling.** Downloaded lead data is treated as untrusted input. The app never sends email automatically, never scrapes restricted sites, and never collects private contact information. |
| CORE-08 | **Simple distribution.** The release is a Windows ZIP (with `launch.bat`, `tg_sales.exe`, a bundled PostgreSQL and the built web app), published on GitHub Releases. End users need no Python, PostgreSQL, Docker, terminal, or developer tools. |
| CORE-09 | **Platforms.** The local app targets Windows 10 and 11 (x64); the web interface works in current desktop and mobile browsers. |

## 3. Architecture requirements

| ID | Requirement |
|----|-------------|
| ARCH-01 | Presentation, domain, persistence and integration code are separated, and the dependency rules between layers are enforced automatically. |
| ARCH-02 | User data (database, backups, logs, snapshots, attachments, caches, exports, reports, user assets) is stored in `%LOCALAPPDATA%\TatumGames\tg_sales`, never in the program folder. A custom location is used only when explicitly requested, and paths with spaces or Unicode characters work. |
| ARCH-03 | Bundled static assets are read-only and resolvable both from source and from the packaged executable. |
| ARCH-04 | Local logs are structured, rotated, and redact sensitive fields such as contact emails, phone numbers and secrets. |
| ARCH-05 | Errors shown to users explain what happened and suggest a next action; unexpected errors are logged and reported without a silent crash. |
| ARCH-06 | Dependencies are pinned in hash-verified lock files for reproducible setup and builds. |
| ARCH-07 | Automated tests require no network access and never touch the real user data folder. |

## 4. User interface requirements

| ID | Requirement |
|----|-------------|
| UI-01 | The Tatum Games palette (`#a787bd`, `#86c4c2`, `#c7d47f`, `#f6d271`, `#d87b7a`) drives accents, status indicators and charts; derived light and dark backgrounds and text colors are used for body content. |
| UI-02 | Text and control contrast meets WCAG AA in both themes and is verified automatically. |
| UI-03 | A sidebar provides Dashboard, Prospects, Pipeline, Discovery, Playbook, Reports, Resources and Settings & Sync; every screen is reachable by mouse and keyboard. |
| UI-04 | The header provides global search, an Import button, a New prospect button and a visible online/offline state. |
| UI-05 | Notifications (toasts) and errors are clear and suggest a next action. |
| UI-06 | Keyboard navigation, logical focus order, shortcut hints and accessible names/tooltips are provided. |
| UI-07 | Layouts are responsive (phone, tablet, laptop, desktop) with touch-friendly controls and no page-level horizontal scrolling; text stays sharp at any zoom. |
| UI-08 | Views provide empty, loading and error states. |
| UI-09 | Dark and light themes are available; the choice is remembered; the default follows the operating system setting. |
| UI-10 | A user-supplied company logo can be set on the Resources page, with safe image validation and a fallback icon. |
| UI-11 | Slow work (imports, discovery, reports, sync) never blocks the interface. |
| UI-12 | Shared components: cards, date range selectors, sortable/filterable tables, progress and skeletons, undo where safe, and confirmation for destructive actions. |
| UI-13 | Color is never the only carrier of status. |
| UI-14 | Charts are responsive, labeled, and offer an accessible data table. |
| UI-15 | Documentation includes screenshots of both themes. |
| UI-16 | Any first-run sample content is explicitly labeled as optional demo content. |

## 4a. Data requirements

| ID | Requirement |
|----|-------------|
| DATA-01 | PostgreSQL is the authoritative database, with foreign keys, unique constraints, indexes and UTC timestamps; the schema is managed by versioned Alembic migrations. |
| DATA-02 | Every record has a globally unique id, UTC created/updated timestamps, the creating device id and an optional deletion tombstone. |
| DATA-03 | Timestamps are stored in UTC and shown in local time. |
| DATA-04 | Organizations, contacts, games, opportunities, pipeline stages, activities, playbook templates, import jobs, discovery runs, sync exports/imports, conflicts, attachments, snapshots and settings are stored. |
| DATA-05 | One organization can have many contacts, games and opportunities, including opportunities in several product lanes at once; games are linked to developers and publishers without being confused with them. |
| DATA-06 | Contact outreach state distinguishes not contacted, attempted and responded, and preserves unknown values. |
| DATA-07 | Activities are immutable; stage transitions and corrections are recorded with their previous values. |
| DATA-08 | Deletion uses tombstones so it can be synchronized; referential integrity and indexes cover domains, external ids, stages, owners, timestamps and follow-up dates. |
| DATA-09 | The pipeline at any historical moment is reconstructed from transition history, not current state. |
| DATA-10 | Every metric and denominator is defined in a KPI dictionary with deterministic time-zone, deduplication and attribution rules. |
| DATA-11 | Database integrity is checked periodically. |
| DATA-12 | The database is backed up before schema upgrades; databases from newer versions are refused. |
| DATA-13 | The schema is documented and versioned, and migrations are tested. |

## 4b. Prospect and import requirements

| ID | Requirement |
|----|-------------|
| PROS-01 | Each prospect (organization) has a detail view with its contacts, games, opportunities, activity timeline, follow-ups, notes and links. |
| PROS-02 | Prospects and contacts can be added, edited and archived (reversibly); every change is recorded in the activity timeline. |
| PROS-03 | Global search covers names, websites, contacts (name, email, role), games and tags; the list can be filtered by tag, type and archived state. |
| PROS-04 | Several prospects can be selected for bulk tagging, archiving/restoring and CSV export. |
| PROS-05 | Accidental duplicates are prevented (same website domain, contact email or name) while similarly named studios remain allowed. |
| PROS-06 | CSV exports are safe to open in spreadsheet software (formula injection is neutralized). |
| PROS-07 | Only http(s) links are stored and opened; contact details record where they came from. |
| IMP-01 | CSV, Excel `.xlsx` and text files can be imported; UTF-8, UTF-8 with BOM, UTF-16 and a reported Windows-1252 fallback are supported. |
| IMP-02 | Files are size-limited, large files are announced, and password-protected, macro-enabled, legacy and malformed files are refused; formulas and file contents are never executed. |
| IMP-03 | CSV dialects and text formats (delimited, `Field: value`, one value per line) are detected; text that cannot be read reliably is reported instead of guessed. |
| IMP-04 | Columns are mapped from header synonyms with visible confidence and editable choices; ambiguous headers are not guessed. |
| IMP-05 | A wizard guides file → sheet → mapping → row preview → match review → summary → atomic commit → result. |
| IMP-06 | URLs, emails, dates and checkmark/yes/no/unknown values are normalized; outreach status is never inferred from the presence of an email; multiple emails create several contacts only when explicit. |
| IMP-07 | Re-imports are idempotent (import id and row fingerprints); results show created/updated/skipped/error counts; problems can be exported as CSV; the import is logged in history. |
| IMP-08 | Imports are reversible through a transactional undo; existing values are never overwritten. |
| IMP-09 | Only file metadata (name, size, type, hash) is kept, not the file or raw rows. |
| IMP-10 | Imports run in the background with progress and can be cancelled without saving anything. |

## 4c. Pipeline and outreach requirements

| ID | Requirement |
|----|-------------|
| PIPE-01 | A kanban board shows opportunities in user-named, ordered stages; cards can be dragged between stages, with a keyboard alternative. |
| PIPE-02 | Cards show the studio, product lane, owner, last activity, next action (overdue stated in words) and release date. |
| PIPE-03 | The default stages are Discovered, Researching, Contacted, Follow-Up, Interested, Technical Review, Negotiation, Won, Lost, Not a Fit. |
| PIPE-04 | Stages can be renamed, reordered, created and archived (moving their opportunities) without corrupting history or reports; terminal stages are safeguarded. |
| PIPE-05 | The board can be filtered by product lane (data licensing, publisher partnership, MIKROS Marketing); stages can be limited to a lane. |
| PIPE-06 | Every stage change writes an immutable event with from/to stage, actor and time. |
| PIPE-07 | Outreach and interactions are logged as separate events (email, LinkedIn invite/message, phone, meeting, reply, demo, data room shared, technical handoff, proposal, closed) with minimal clicks; nothing is described as sent unless logged. |
| PIPE-08 | Each opportunity supports notes, tasks, a next follow-up date and reason codes for won/lost/not a fit. |
| PIPE-09 | The Dashboard lists overdue and due-today follow-ups and tasks. |
| PIPE-10 | Data-licensing opportunities offer a copyable technical handoff draft for the technical lead, with no automatic sending and an explicit authorized-review notice. |
| PIPE-11 | Several opportunities can exist for the same organization; the board stays consistent across restarts. |

## 4d. Dashboard and KPI requirements

| ID | Requirement |
|----|-------------|
| KPI-01 | Period selector (7 days, 30 days, 3/6/12 months, custom) with optional salesperson and product-lane filters. |
| KPI-02 | Cards for leads added, contacts added, unique contacts attempted, replies, active opportunities, technical handoffs, proposals, won, lost, win rate (with its denominator), follow-ups due and overdue. |
| KPI-03 | Stage distribution, median time in stage and stage conversion rates with clear denominators. |
| KPI-04 | Trend, funnel and release-window charts, recent activity and lead-source quality; chart data exportable as CSV. |
| KPI-05 | Every card drills down to the underlying records. |
| KPI-06 | `0` and "not available" are displayed distinctly. |
| KPI-07 | Definitions follow the KPI dictionary exactly (corrections, daylight saving, deletions, attribution); charts reconcile with card totals; snapshots are never a data source. |
| KPI-08 | Calculations run on a worker with a refresh indicator, are cached until data changes, and handle 100,000 contacts and long histories without freezing; a benchmark script is provided. |
| KPI-09 | The empty dashboard explains what to do next. |

## 4e. Game discovery requirements

| ID | Requirement |
|----|-------------|
| DISC-01 | Suggest studios with Steam releases in a configurable upcoming window (default 90 days) or recent window (default 150 days). |
| DISC-02 | Show title, Steam app id/link, release date and certainty, developer/publisher, genres/tags, website/contact source, fit explanation, last checked, confidence and CRM duplicate state. |
| DISC-03 | Filter by platform, timing, self-published (indie) status, language, genre, score and CRM state; region is not available from the source and is documented as such. |
| DISC-04 | Use only permitted public sources with rate limiting, caching, attribution and robots.txt compliance; never bypass access controls; store provenance URL and retrieval time. |
| DISC-05 | Offer a compliant alternative when search is insufficient (adding games by Steam link or app id). |
| DISC-06 | Source adapters behind a `GameSourceAdapter` protocol with feature flags; background fetch with cancellation, retries/backoff and a stale cache. |
| DISC-07 | Business contacts only from the store's published contact or the official studio website; statuses not found / needs verification / verified source; never invent addresses. |
| DISC-08 | Human review queue, dedupe by app id and domain, manual Save to Prospects. |
| DISC-09 | Transparent, configurable scoring rules; no unsupported predictions. |
| DISC-10 | Degrade gracefully offline and on errors (403/429/network); never show stale results as current. |

## 4f. Playbook requirements

| ID | Requirement |
|----|-------------|
| PB-01 | Templates have a title, message, channel (email, LinkedIn connection note, LinkedIn message, phone, follow-up, publisher, data buyer), audience, category, pipeline stage, user-defined label and tags, internal notes, author, favorite flag, approved status and active/archived state. |
| PB-02 | Search across title, message and metadata; filter by channel, audience, category, tag, favorites, approved and archived. |
| PB-03 | Create, edit, duplicate, archive and restore templates; every saved edit is a revision with author and summary; any earlier revision can be restored without losing history. |
| PB-04 | Placeholders `{studio_name}`, `{game_title}`, `{contact_name}`, `{release_date}`, `{platform}` are filled from a chosen prospect (contact and game selectable, values editable) with a live preview. |
| PB-05 | Missing or unknown placeholders are explained in the preview, and copying text that still contains placeholders requires explicit confirmation. |
| PB-06 | One-click copy with visible feedback; tg_sales never sends messages and never connects to LinkedIn or other automation. |
| PB-07 | Approval status is visible; editing the text of an approved template removes the approval. Example templates start unapproved, and their figures and incentives are labeled as claims and selective offers that need business approval. |
| PB-08 | Outcome notes (reply, meeting, no reply, not interested, other) are recorded manually per template, with counts shown. |
| PB-09 | Templates, revisions and outcome notes are ordinary database records, included in sync and backups. |

## 4g. Reports and snapshot requirements

| ID | Requirement |
|----|-------------|
| RPT-01 | Report periods: trailing 7 days, 30 days, 1, 3, 6 and 12 months, previous calendar month/quarter/year, and custom; boundaries are explained before generating. |
| RPT-02 | Reports are produced as a PDF, CSV data tables and an optional HTML preview, without overwriting earlier reports. |
| RPT-03 | Sections: executive summary, lead acquisition, contacted/responded, stage distribution at period start and end, transitions, wins/losses with reasons, activity by salesperson and product lane, follow-up backlog, source effectiveness, trend charts, notable progress, data quality caveats. |
| RPT-04 | Counts reference their definitions; unavailable data is marked "Not available"; no qualitative insights are fabricated. |
| RPT-05 | The same period and filters give the same counts in the dashboard and the report. |
| RPT-06 | One-click dashboard snapshot (visible area or whole dashboard) rendered from the dashboard's own content in the browser (never a screen capture), saved as `dashboard_snapshot_YYYY-MM-DD_<epoch_ms>.png` with registered metadata (filters, time, path, app version); names never collide. |
| RPT-07 | Reports and snapshots can be browsed, opened, exported and deleted; exports never overwrite without confirmation; only files inside the app's folders are deleted. |
| RPT-08 | PDF output is legible (print-resolution charts with legends, page breaks between major sections, page numbers); snapshots are sharp on high-DPI displays. |

## 4h. Collaboration (offline sync) requirements

| ID | Requirement |
|----|-------------|
| SYNC-01 | Export changes since the last export, or everything, to `tg_sales_sync_<person>_<YYYYMMDDTHHMMSSZ>_<shortid>.zip` with a manifest (schema version, export id, source computer, time, counts, per-file SHA-256). |
| SYNC-02 | Deltas come from a database change ledger (not `updated_at`); records received from colleagues are forwarded onward without loops. |
| SYNC-03 | Imports are previewed and validated (safe ZIP paths, size and compression limits, hashes, schema version, types, identifiers, references) and applied in one transaction after a backup; failures change nothing. |
| SYNC-04 | Importing the same package twice changes nothing; out-of-order packages are handled (records wait for what they refer to). |
| SYNC-05 | Records changed on both computers are shown field by field and resolved by the user, never silently overwritten; resolutions propagate without new conflicts. |
| SYNC-06 | Possible duplicate organizations and contacts (same domain, name or email) are flagged but never merged automatically. |
| SYNC-07 | Optional passphrase encryption (AES-256-GCM, scrypt key derivation); wrong passphrases and tampering are detected. |
| SYNC-08 | Sync history, conflict resolutions and per-computer settings are kept locally; device-only data never leaves the computer. |

## 4i. Settings, resources and backups

| ID | Requirement |
|----|-------------|
| OPS-01 | Settings: salesperson name, theme, time zone and number format, import date order, discovery windows and cache age, backup interval and retention. |
| OPS-02 | Resources page: safe http(s) bookmarks (shared through sync) and local folder shortcuts (this computer only); company logo with safe image handling. |
| OPS-03 | Verified backups (`pg_dump`) on request, on a schedule, and automatically before upgrades, imports, sync imports and restores; retention keeps the latest N plus monthly copies. |
| OPS-04 | Restore verifies the backup, restores into a temporary database, checks it, then swaps; the previous database is kept until the next restore. |
| OPS-05 | Data from the earlier desktop version (SQLite) can be transferred: original untouched, ids and history preserved, repeatable without duplicates, verified, with a report. |
| OPS-06 | A health check confirms schema, safeguards and readability; About shows version, schema, sync id and data folder. |

## 4j. Web, mobile and hosting requirements

| ID | Requirement |
|----|-------------|
| WEB-01 | `launch.bat` verifies the runtime, starts PostgreSQL, applies migrations safely, serves the API and web app on 127.0.0.1, opens the browser, prevents duplicate instances and stops cleanly (`stop.bat`). |
| WEB-02 | Installable PWA (manifest, icons, service worker caching only the app shell; CRM data is never cached by the service worker). |
| WEB-03 | The HTTP API is documented, versioned with the app, and reusable by a future mobile app. |
| WEB-04 | Configuration comes from environment variables (database URL, origins, environment, logging, ports); nothing is hard-wired to localhost except safe defaults. |
| WEB-05 | Security: loopback-only by default, refusal to listen on a network without sign-in, host and origin checks, anti-forgery header, strict security headers, safe errors, validated uploads. |
| WEB-06 | Docker Compose (PostgreSQL + app, localhost-only ports, health checks, persistent volumes) and Dockerfiles for future hosting. |

## 5. Definition of done

The product is complete when, on a clean Windows 10/11 machine, a user can
perform the following journey without errors or data loss:

| ID | Step |
|----|------|
| DOD-01 | Download the release ZIP from GitHub Releases and extract it. |
| DOD-02 | Double-click `launch.bat`; the app opens in the browser. |
| DOD-03 | Complete first-run setup. |
| DOD-04 | Import leads from a file. |
| DOD-05 | Discover leads online. |
| DOD-06 | Move opportunities through the pipeline. |
| DOD-07 | Log sales activities. |
| DOD-08 | Export a sync package and import it on another computer. |
| DOD-09 | Produce a report. |
| DOD-10 | Take a dashboard snapshot. |
| DOD-11 | Close and reopen the application with no data loss. |
| DOD-12 | The repository contains synthetic test fixtures and documentation screenshots. |

## 6. Traceability matrix

Module paths are relative to `src/tg_sales/` unless they start with `web/`,
`docs/`, `deploy/` or `scripts/`. Status values: **Implemented** (code and
automated tests exist and pass), **Verified** (also exercised end to end in a
browser against the real server and PostgreSQL by the Playwright workflow, or
in the packaged release build).

| ID | Implementation | Automated tests | UI location | Status |
|----|----------------|-----------------|-------------|--------|
| CORE-01 | whole application | full suite | — | Verified |
| CORE-02 | whole application | full suite | — | Implemented |
| CORE-03 | whole application | full suite | — | Verified |
| CORE-04 | whole application | full suite | — | Verified |
| CORE-05 | whole application | full suite | — | Implemented |
| CORE-06 | whole application | full suite | — | Verified |
| CORE-07 | whole application | full suite | — | Implemented |
| CORE-08 | whole application | full suite | — | Verified |
| CORE-09 | whole application | full suite | — | Implemented |
| ARCH-01 | layer packages under `src/tg_sales/` | `tests/unit/test_architecture.py` | — | Implemented |
| ARCH-02 | `config.py` (`AppPaths`) | `tests/unit/test_config.py` | — | Implemented |
| ARCH-03 | `config.py` (`resource_path`) | `tests/unit/test_config.py` | — | Implemented |
| ARCH-04 | `logging_setup.py` (incl. URL passwords) | `tests/unit/test_logging_setup.py` | — | Implemented |
| ARCH-05 | `errors.py`, `api/security.py` (error envelope), `web/src/components/ui/misc.tsx` (`ErrorState`) | `tests/api/test_api_security.py`, `web/src/test/components.test.tsx` | All screens | Implemented |
| ARCH-06 | `requirements.lock`, `requirements-dev.lock`, `web/package-lock.json` | CI (`.github/workflows/ci.yml`) | — | Implemented |
| ARCH-07 | `tests/pg.py` (throwaway PostgreSQL), `tests/e2e_server.py` (fake Steam) | entire suite | — | Implemented |
| UI-01 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| UI-02 | `web/src/index.css` (contrast-safe tokens) | `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| UI-03 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Verified |
| UI-04 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Verified |
| UI-05 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| UI-06 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| UI-07 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Verified |
| UI-08 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| UI-09 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Verified |
| UI-10 | `services/branding.py`, `web/src/features/resources/ResourcesPage.tsx` | `tests/api/test_api_flows.py` | Resources › Company logo | Implemented |
| UI-11 | `api/jobs.py`, `web/src/lib/jobs.ts` | `tests/api/test_api_flows.py` | Imports, Discovery, Reports, Sync, Backups | Implemented |
| UI-12 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| UI-13 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| UI-14 | `web/src/components/ChartCard.tsx` | `web/src/test/components.test.tsx` | Dashboard charts | Implemented |
| UI-15 | `docs/screenshots/web_*.png`, `web/e2e/03-screens.spec.ts` | — | — | Implemented |
| UI-16 | `web/src/components/`, `web/src/components/layout/AppShell.tsx` | `web/src/test/components.test.tsx`, `web/e2e/02-responsive.spec.ts` | All screens | Implemented |
| DATA-01 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-02 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-03 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-04 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-05 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-06 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-07 | `services/ledger.py`, PostgreSQL trigger `trg_activities_immutable` | `tests/integration/test_entities.py` | Opportunity › History | Implemented |
| DATA-08 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-09 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-10 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| DATA-11 | `db/database.py` (`check_integrity`), `api/routers/system.py` | `tests/integration/test_migrations.py` | Settings & Sync › About | Implemented |
| DATA-12 | `db/database.py` (`migrate` + pre-upgrade backup) | `tests/integration/test_migrations.py` | — | Implemented |
| DATA-13 | `db/models.py`, `db/migrations_pg/`, `db/database.py` | `tests/integration/test_migrations.py`, `tests/integration/test_entities.py` | — | Implemented |
| PROS-01 | `services/prospects.py`, `api/routers/prospects.py`, `web/src/features/prospects/` | `tests/integration/test_prospect_service.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Prospects | Verified |
| PROS-02 | `services/prospects.py`, `api/routers/prospects.py`, `web/src/features/prospects/` | `tests/integration/test_prospect_service.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Prospects | Verified |
| PROS-03 | `services/prospects.py`, `api/routers/prospects.py`, `web/src/features/prospects/` | `tests/integration/test_prospect_service.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Prospects | Implemented |
| PROS-04 | `services/prospects.py`, `api/routers/prospects.py`, `web/src/features/prospects/` | `tests/integration/test_prospect_service.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Prospects | Implemented |
| PROS-05 | `services/prospects.py`, `api/routers/prospects.py`, `web/src/features/prospects/` | `tests/integration/test_prospect_service.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Prospects | Implemented |
| PROS-06 | `services/csv_export.py`, `web/src/lib/csv.ts` | `tests/integration/test_prospect_service.py`, `web/src/lib/lib.test.ts` | Prospects › Export CSV | Implemented |
| PROS-07 | `services/prospects.py`, `api/routers/prospects.py`, `web/src/features/prospects/` | `tests/integration/test_prospect_service.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Prospects | Implemented |
| IMP-01 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-02 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-03 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-04 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-05 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Verified |
| IMP-06 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-07 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-08 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-09 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| IMP-10 | `services/imports.py`, `services/import_files.py`, `api/routers/imports.py`, `web/src/features/imports/` | `tests/integration/test_import_service.py`, `tests/integration/test_import_files.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Header › Import | Implemented |
| PIPE-01 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Verified |
| PIPE-02 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Implemented |
| PIPE-03 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Implemented |
| PIPE-04 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Implemented |
| PIPE-05 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Implemented |
| PIPE-06 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Verified |
| PIPE-07 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Verified |
| PIPE-08 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Verified |
| PIPE-09 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Implemented |
| PIPE-10 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Implemented |
| PIPE-11 | `services/pipeline.py`, `api/routers/pipeline.py`, `web/src/features/pipeline/` | `tests/integration/test_pipeline_service.py`, `tests/api/test_api_flows.py`, `web/src/test/components.test.tsx`, `web/e2e/01-workflow.spec.ts` | Pipeline | Implemented |
| KPI-01 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Verified |
| KPI-02 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Verified |
| KPI-03 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Implemented |
| KPI-04 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Implemented |
| KPI-05 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Implemented |
| KPI-06 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Implemented |
| KPI-07 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Implemented |
| KPI-08 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Implemented |
| KPI-09 | `domain/kpi.py`, `services/kpis.py`, `api/routers/dashboard.py`, `web/src/features/dashboard/` | `tests/integration/test_kpis.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Dashboard | Implemented |
| DISC-01 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-02 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-03 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-04 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-05 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-06 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-07 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-08 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Verified |
| DISC-09 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| DISC-10 | `services/discovery.py`, `integrations/steam.py`, `api/routers/discovery.py`, `web/src/features/discovery/` | `tests/integration/test_discovery_service.py`, `tests/integration/test_steam_sources.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Discovery | Implemented |
| PB-01 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-02 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-03 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-04 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-05 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-06 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-07 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-08 | `services/playbook.py`, `domain/playbook.py`, `api/routers/playbook.py`, `web/src/features/playbook/` | `tests/integration/test_playbook_service.py`, `tests/unit/test_playbook_rules.py`, `tests/api/test_api_flows.py` | Playbook | Implemented |
| PB-09 | `db/models.py` (`SYNCED_TABLES`), `services/backups.py` | `tests/integration/test_sync.py`, `tests/integration/test_backups.py` | — | Implemented |
| RPT-01 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Implemented |
| RPT-02 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Verified |
| RPT-03 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Implemented |
| RPT-04 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Implemented |
| RPT-05 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Implemented |
| RPT-06 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Verified |
| RPT-07 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Implemented |
| RPT-08 | `reports/`, `services/report_catalog.py`, `services/snapshots.py`, `api/routers/reports.py`, `web/src/features/reports/`, `web/src/features/dashboard/` | `tests/integration/test_reports.py`, `tests/integration/test_snapshots.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Reports; Dashboard › Snapshot | Implemented |
| SYNC-01 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Verified |
| SYNC-02 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Implemented |
| SYNC-03 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Verified |
| SYNC-04 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Verified |
| SYNC-05 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Implemented |
| SYNC-06 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Implemented |
| SYNC-07 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Implemented |
| SYNC-08 | `sync/package.py`, `sync/engine.py`, `api/routers/collaboration.py`, `web/src/features/settings/SyncPanel.tsx` | `tests/integration/test_sync.py`, `tests/api/test_api_flows.py`, `web/e2e/01-workflow.spec.ts` | Settings & Sync › Sync | Implemented |
| OPS-01 | `services/app_settings.py`, `services/resources.py`, `services/branding.py`, `services/backups.py`, `legacy/`, `web/src/features/settings/`, `web/src/features/resources/` | `tests/integration/test_backups.py`, `tests/integration/test_legacy_transfer.py`, `tests/api/test_api_flows.py` | Settings & Sync; Resources | Implemented |
| OPS-02 | `services/app_settings.py`, `services/resources.py`, `services/branding.py`, `services/backups.py`, `legacy/`, `web/src/features/settings/`, `web/src/features/resources/` | `tests/integration/test_backups.py`, `tests/integration/test_legacy_transfer.py`, `tests/api/test_api_flows.py` | Settings & Sync; Resources | Implemented |
| OPS-03 | `services/app_settings.py`, `services/resources.py`, `services/branding.py`, `services/backups.py`, `legacy/`, `web/src/features/settings/`, `web/src/features/resources/` | `tests/integration/test_backups.py`, `tests/integration/test_legacy_transfer.py`, `tests/api/test_api_flows.py` | Settings & Sync; Resources | Implemented |
| OPS-04 | `services/app_settings.py`, `services/resources.py`, `services/branding.py`, `services/backups.py`, `legacy/`, `web/src/features/settings/`, `web/src/features/resources/` | `tests/integration/test_backups.py`, `tests/integration/test_legacy_transfer.py`, `tests/api/test_api_flows.py` | Settings & Sync; Resources | Implemented |
| OPS-05 | `services/app_settings.py`, `services/resources.py`, `services/branding.py`, `services/backups.py`, `legacy/`, `web/src/features/settings/`, `web/src/features/resources/` | `tests/integration/test_backups.py`, `tests/integration/test_legacy_transfer.py`, `tests/api/test_api_flows.py` | Settings & Sync; Resources | Implemented |
| OPS-06 | `services/app_settings.py`, `services/resources.py`, `services/branding.py`, `services/backups.py`, `legacy/`, `web/src/features/settings/`, `web/src/features/resources/` | `tests/integration/test_backups.py`, `tests/integration/test_legacy_transfer.py`, `tests/api/test_api_flows.py` | Settings & Sync; Resources | Implemented |
| WEB-01 | `launcher/`, `api/`, `web/vite.config.ts`, `deploy/`, `launch.bat` | `tests/api/test_api_security.py`, `web/e2e/01-workflow.spec.ts`, `web/e2e/02-responsive.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| WEB-02 | `web/vite.config.ts` (PWA), `web/public/icons/` | manifest and service worker served by `launch.bat` (manual check) | Browser › Install | Implemented |
| WEB-03 | `api/`, `docs/API.md` (generated) | `scripts/generate_api_types.py --check`, `tests/api/` | — | Implemented |
| WEB-04 | `api/settings.py`, `deploy/.env.example` | `tests/api/test_api_security.py` | — | Implemented |
| WEB-05 | `launcher/`, `api/`, `web/vite.config.ts`, `deploy/`, `launch.bat` | `tests/api/test_api_security.py`, `web/e2e/01-workflow.spec.ts`, `web/e2e/02-responsive.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| WEB-06 | `deploy/Dockerfile`, `deploy/docker-compose.yml` | not run (Docker unavailable on the build computer) | — | Implemented (not run) |
| DOD-01 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Implemented (release not published) |
| DOD-02 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Implemented |
| DOD-03 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-04 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-05 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Implemented (fake Steam in tests; live endpoints to re-check) |
| DOD-06 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-07 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-08 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-09 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-10 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-11 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
| DOD-12 | release ZIP (`scripts/build_windows.ps1`) | `web/e2e/01-workflow.spec.ts`, `scripts/smoke_test.ps1` | — | Verified |
