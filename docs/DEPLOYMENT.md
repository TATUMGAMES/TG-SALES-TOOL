# Installation, distribution and deployment

## 1. Salespeople: the Windows release (recommended)

**What is in the release ZIP** (`tg_sales_windows_x64_v<version>.zip`, about
95 MB):

| Item | Purpose |
|------|---------|
| `launch.bat` | Starts tg_sales and opens the browser |
| `stop.bat` | Stops tg_sales and its database |
| `tg_sales.exe`, `_internal\` | The server (Python and all libraries bundled; built with PyInstaller) |
| `runtime\postgresql\` | Portable PostgreSQL 18 (official EnterpriseDB Windows binaries) |
| `web\` | The built web app |
| `README.txt`, `LICENSE` | Short instructions, license |

**Prerequisites:** Windows 10 or 11 (64-bit) and a current browser (Edge,
Chrome or Firefox). Nothing else: no Python, PostgreSQL, Docker, Node.js,
administrator rights or SQL. This was tested by building the ZIP and running
`scripts\smoke_test.ps1` and the API checks against the extracted folder on a
Windows 10 computer; a test on a freshly installed Windows computer is still
recommended before wide rollout.

**First start:** `launch.bat` creates the private database (about a minute)
under `%LOCALAPPDATA%\TatumGames\tg_sales\postgres`, with random passwords
stored in `credentials.json` in that folder. The database listens on
`127.0.0.1:54329` only and accepts password (SCRAM) logins from this computer
only. The app listens on `127.0.0.1:8765` (or the next free port).

**Update:** stop tg_sales, extract the new ZIP (replace the old folder or use a
new one), start `launch.bat`. Data is in `%LOCALAPPDATA%`, never in the
program folder; schema upgrades run automatically after a verified backup. A
database written by a newer version is refused with a clear message.

**Uninstall:** delete the program folder. To also delete all data, delete
`%LOCALAPPDATA%\TatumGames\tg_sales` (download a backup first if you may need
the data).

**Data folder layout** (`%LOCALAPPDATA%\TatumGames\tg_sales`):

```
postgres\        database cluster, credentials.json, server.log
backups\         verified pg_dump backups (+ .json descriptions)
reports\         report folders (PDF, HTML, CSV, manifest)
snapshots\       dashboard snapshot PNGs
exports\sync\    sync packages you exported
assets\          company logo
logs\            app log (rotated, contact details redacted)
cache\           Steam cache, upload staging (temporary)
migration_reports\  reports of desktop-data transfers
```

## 2. Developers and testers: running from source

```bat
setup.bat      :: needs Python 3.13 and Node.js 22+; downloads PostgreSQL (SHA-256 verified)
launch.bat     :: same launcher as the release, using .venv and web\dist
```

`--data-dir D:\somewhere` (for `launch.bat`, `stop.bat` or the launcher) uses
another data folder, e.g. for testing without touching real data.

Building the release: `scripts\build_windows.ps1` (output in `dist\`, with
`SHA256SUMS.txt`), then `scripts\smoke_test.ps1 -Folder dist\tg_sales_windows_x64_v<version>`.
The GitHub `Release` workflow does the same for a pushed `v*.*.*` tag and
creates a **draft** release; publishing it is a manual decision.

## 3. Docker (optional)

For computers with Docker, or as the starting point for hosting:

```bash
cp deploy/.env.example deploy/.env      # set TG_SALES_DB_PASSWORD
docker compose -f deploy/docker-compose.yml --env-file deploy/.env up -d --build
# open http://127.0.0.1:8765
```

- `db`: PostgreSQL 18.4 with a persistent volume, health check, published on
  `127.0.0.1` only.
- `app`: the API and web app (`deploy/Dockerfile`: Node build stage, Python
  runtime with PostgreSQL 18 client tools for backups and DejaVu fonts for
  PDFs), running as a non-root user, published on `127.0.0.1` only.
- Backups are stored in the `appdata` volume (`/data/backups`). Restore needs
  an administrator database URL (`TG_SALES_ADMIN_DATABASE_URL`); without it
  the app offers download only.

> Status: the compose file and Dockerfile are written and their image tags
> verified, but they could not be run on the development computer (no
> hardware virtualization). Run them once before relying on them.

## 4. Configuration (environment variables)

All settings use the `TG_SALES_` prefix (`src/tg_sales/api/settings.py`). The
launcher sets the database ones automatically for the local app.

| Variable | Default | Meaning |
|----------|---------|---------|
| `TG_SALES_DATABASE_URL` | — (required) | `postgresql://user:password@host:port/db` |
| `TG_SALES_ADMIN_DATABASE_URL` | — | Account allowed to create/rename databases (restore) |
| `TG_SALES_HOST` / `TG_SALES_PORT` | `127.0.0.1` / `8765` | Listen address |
| `TG_SALES_ENVIRONMENT` | `production` | `development` enables `/api/docs` and the Vite origin |
| `TG_SALES_ALLOWED_ORIGINS` | — | Extra browser origins (comma-separated) |
| `TG_SALES_DATA_DIR` | `%LOCALAPPDATA%\TatumGames\tg_sales` | Data folder |
| `TG_SALES_STATIC_DIR` | `web/dist` | Built web app to serve |
| `TG_SALES_PG_BIN` | bundled runtime / `PATH` | Folder with `pg_dump`/`pg_restore` |
| `TG_SALES_LOG_LEVEL` | `INFO` | Log level |
| `TG_SALES_CONTAINER_LOCAL_ONLY` | `false` | Allow listening on the container interface (compose publishes on 127.0.0.1) |
| `TG_SALES_PDF_FONT` | Segoe UI / Arial / DejaVu | TrueType font for PDF reports |

Secrets belong in the environment or `deploy/.env` (git-ignored), never in
source files or the web app.

## 5. Future hosting for a team

What is ready:

- Separate web app, API and database; stateless HTTP API documented in
  [API.md](API.md); environment-based configuration; Docker images.
- PostgreSQL as the shared store, with ownership, authorship and an audit
  trail (activity ledger, change log) already in the schema.
- Background jobs and file storage behind services (to be moved to shared
  storage when hosted).

What must be added **before** the CRM is reachable from a network
(the server refuses to start on a non-loopback address until then):

1. User accounts and sign-in (e.g. company single sign-on via OpenID Connect),
   replacing the per-device "current salesperson".
2. Authorization: roles (salesperson, manager, admin) and record ownership
   rules on every endpoint; per-user audit of reads and exports if required.
3. HTTPS termination (reverse proxy) and secure cookies/CSRF tokens instead of
   the local-only header check; rate limiting.
4. Shared storage for reports, snapshots and backups (object storage), and a
   managed backup policy for the database.
5. A decision on offline sync: keep it for laptops that work offline, or
   replace it with direct access to the shared database.
