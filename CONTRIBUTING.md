# Contributing to TG Sales CRM

Thank you for helping. Bug reports, ideas, documentation fixes and code are
all welcome.

## Reporting a bug

Open an issue on [GitHub](https://github.com/TATUMGAMES/TG-SALES-TOOL/issues)
with:

1. What you did (numbered steps), what you expected and what happened.
2. The version and schema revision (Settings & Sync › About).
3. Relevant lines from the log
   (`%LOCALAPPDATA%\TatumGames\tg_sales\logs\tg_sales.log`; contact details are
   already redacted).

**Never attach real prospect lists, contact details, databases, backups or
sync packages.** Make a small synthetic example instead. Report security
problems privately as described in [docs/SECURITY.md](docs/SECURITY.md), not
in a public issue.

## Suggesting an improvement

Open an issue describing the problem you want solved and who it helps,
before writing a large change. Features should work for any organization:
put organization-specific values in settings, presets or data, not in code.

## Submitting a pull request

1. Fork the repository and create a branch from `main`.
2. Set up as described in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md)
   (`setup.bat`, then the development dependencies).
3. Make the change with tests (see below) and update the documentation it
   affects: the README, `docs/`, `CHANGELOG.md`, and `docs/DATA_MODEL.md` for
   any schema change.
4. Run the quality gate and make sure it passes:

   ```powershell
   powershell -File scripts\check.ps1 -E2E
   ```

5. Open the pull request with a short description of what and why.

By submitting a contribution you agree that it is licensed under the
[Apache License 2.0](LICENSE), as section 5 of the license describes. You
keep the copyright in your contribution.

## Running tests

```powershell
.venv\Scripts\python -m pytest                    # backend: unit, integration (PostgreSQL), API
cd web; npm test                                  # web unit tests
cd web; npm run build; npm run e2e                # browser tests (Playwright)
```

The backend tests start a throwaway PostgreSQL from `runtime\postgresql`, or
use `TG_SALES_TEST_DATABASE_URL`. They never touch your real data. See
[docs/TESTING.md](docs/TESTING.md).

## Coding conventions

- **Structure:** pure rules in `src/tg_sales/domain/` (no database, network or
  web imports; enforced by `tests/unit/test_architecture.py`), use cases in
  `services/`, queries in `repositories/`, one FastAPI router per feature in
  `api/routers/`, one folder per screen in `web/src/features/`.
- **Types:** `mypy --strict` and TypeScript strict mode must pass. After
  changing the API, run `scripts\generate_api_types.py` to regenerate
  `docs/API.md` and `web/src/lib/api-types.ts`.
- **Style:** `ruff format` and `ruff check` (line length 100).
- **Database:** every schema change is an Alembic migration in
  `src/tg_sales/db/migrations_pg/versions/` that never loses existing data,
  with a test, and is documented in `docs/DATA_MODEL.md`.
- **No hard-coded organization data:** read lanes from `/api/lanes`
  (`useLanes()`), branding from `/api/branding` (`useBranding()`), and offer
  company-specific content as optional presets.
- **User-facing text:** plain language, saying what happened and what to do
  next.
- **License headers:** new source files start with the Apache 2.0 header; run
  `.venv\Scripts\python scripts\license_headers.py`. Don't add headers to
  generated files or change the notices of third-party code.
- **Privacy:** test data must be synthetic and clearly invented.
