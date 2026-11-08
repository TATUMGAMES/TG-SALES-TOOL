# Testing

All tests use synthetic data and never touch the real data folder or the
network.

| Suite | Tool | Where | What it covers |
|-------|------|-------|----------------|
| Unit | Pytest | `tests/unit/` | Domain rules (normalization, importing, pipeline, KPIs, playbook, periods), configuration, logging redaction, architecture rules, schema documentation |
| Integration | Pytest + PostgreSQL | `tests/integration/` | Services and repositories on a real PostgreSQL: prospects, imports, pipeline, KPIs (history, corrections, time zones), discovery (fake Steam), playbook, reports (PDF/CSV/HTML), snapshots, migrations, backups and restore, desktop-data transfer, multi-computer sync |
| API | Pytest + FastAPI TestClient | `tests/api/` | Every API area end to end over HTTP against PostgreSQL; security controls (anti-forgery header, host and origin checks, headers, error envelope, SQL injection, refusal to listen on a network) |
| Web unit | Vitest + React Testing Library | `web/src/**/*.test.ts(x)` | API client errors, CSV safety, formatting, form validation and duplicate flow, pipeline menu moves and reasons, chart data tables, error states, navigation |
| Browser | Playwright | `web/e2e/` | The full workflow on desktop (onboarding, create prospect, import file, pipeline drag and menu moves, outreach, won with reason, snapshot, PDF report, discovery and save, sync export and import incl. repeat, restart persistence) and responsive checks on desktop, tablet and phone (navigation, no horizontal overflow, touch moves, themes) |
| Release | PowerShell | `scripts/smoke_test.ps1` | Starts a built release folder with a temporary data folder, checks health, the web app and saving a record, stops it |

## Running

```powershell
powershell -File scripts\check.ps1 -E2E     # everything (about 6 minutes)

.venv\Scripts\python -m pytest                       # backend (unit, integration, API)
.venv\Scripts\python -m pytest tests\integration\test_sync.py -q
cd web; npm test                                     # web unit tests
cd web; npm run build; npm run e2e                   # browser tests (needs a build)
cd web; npx playwright test --project=mobile         # one screen size
```

## How the database is provided

`tests/pg.py` starts a throwaway PostgreSQL cluster from the portable
binaries in `runtime/` (in a temporary folder, on a free port), migrates a
template database once, and gives every test its own copy
(`CREATE DATABASE … TEMPLATE`). In CI, `TG_SALES_TEST_DATABASE_URL` points to a
PostgreSQL service instead. Backup tests need `pg_dump`/`pg_restore` (from the
runtime or `PATH`).

The browser tests run `tests/e2e_server.py`: the real server and web app with
a throwaway database and the synthetic Steam store
(`tests/fixtures/steam/store_responses.json`). Its database lives in
`web/.e2e/run` and is stopped by the Playwright teardown.

## Documentation screenshots

```powershell
cd web; $env:SCREENSHOTS=1; npx playwright test --project=desktop --project=mobile
```

writes `docs/screenshots/web_*.png` from the synthetic workflow data.

## Performance

`scripts\benchmark_kpis.py` loads 100,000 contacts (50,000 prospects) and
500,000 activities. Measured on the development laptop (Windows 10, local
PostgreSQL 18):

| Operation | Time |
|-----------|------|
| Dashboard, last 7 days / 3 months / 12 months (first calculation) | 1.7 s / 2.4 s / 5.2 s |
| Dashboard, repeated (cached until data changes) | 0.13–0.20 s |
| Prospect list, first page | 17 ms |
| Prospect search by name or email domain | 0.11–0.12 s |
| Prospect detail | 30 ms |

## Known gaps

- Docker images and compose are not exercised by the automated tests.
- Live Steam endpoints are only checked manually (tests use the fake store).
- A first run on a freshly installed Windows computer (outside the
  development machine) has not been recorded yet.
