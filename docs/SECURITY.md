# Security and privacy

## Threat model (local installation)

| Threat | Controls |
|--------|----------|
| Other computers reaching the CRM | Server and database listen on `127.0.0.1` only; `pg_hba.conf` accepts loopback SCRAM logins only; the server refuses to start on any other address until sign-in exists (Docker publishes on `127.0.0.1` only) |
| Malicious web pages attacking the local server (CSRF, DNS rebinding) | Host header must be `127.0.0.1`/`localhost`; state-changing requests need the `X-TG-Sales` header (a cross-site page cannot send it without a CORS preflight, which is refused); unknown `Origin` refused; CORS closed by default |
| Script injection in the app | React escaping; strict Content-Security-Policy (`script-src 'self'`, no inline scripts, `frame-ancestors 'none'`, `object-src 'none'`); report HTML previews served sandboxed with no scripts; only `http(s)` links are stored and opened (`rel="noopener noreferrer"`) |
| SQL injection | All queries are parameterized through SQLAlchemy/psycopg; tested with hostile input |
| Malicious import files | Size limits, extension and content checks, macro-enabled/legacy/encrypted workbooks refused, XLSX compression-bomb limits, formulas never evaluated, row/column limits; uploaded files are kept only during the import and deleted afterwards |
| Malicious sync packages | Name allow-list (no paths), size and ratio limits, per-file SHA-256, schema/format checks, full value validation, one transaction, backup first; optional authenticated encryption |
| Malicious images (logo, snapshots) | Decoded and re-encoded with Pillow (decompression-bomb limit, dimension limit, PNG/JPEG/BMP/WebP only, no SVG) |
| Path traversal (downloads, deletes) | Every file path from the database or a URL is resolved and must stay inside its own data folder; names are pattern-checked |
| Spreadsheet formula injection in exports | Cells starting with `=`, `+`, `-`, `@`, tab or carriage return are neutralized in every CSV (server and browser) |
| Data loss | Verified backups before upgrades, imports, sync imports and restores, plus scheduled backups with retention; restore into a temporary database and swap; immutable activity ledger |
| Leaking secrets or contacts in logs | Logs redact email addresses, phone numbers, `password=`-style values and passwords inside URLs; errors shown to users never include internal details |
| Supply chain | Hash-pinned Python lock files, exact npm versions with a lock file, two-week cool-down on new releases, `pip-audit` and `npm audit` in CI, verified SHA-256 for the PostgreSQL download |

## What stays on the computer and what leaves it

- Stays: the database, backups, reports, snapshots, logs and settings, all in
  `%LOCALAPPDATA%\TatumGames\tg_sales`.
- Leaves only when you act: **Game discovery** requests public Steam store
  pages and the official studio website of a game (with a polite request rate
  and robots.txt respected); **sync packages** you export and send yourself;
  **downloads** you save (backups, reports, CSV).
- No telemetry, no analytics, no automatic emails or messages, no LinkedIn or
  browser automation.

## Encryption at rest

Local-first is not the same as encrypted: anyone who can sign in to your
Windows account can read the database files and backups. Protect laptops with
BitLocker (or your company's disk encryption) and a screen lock. Sync packages
can be encrypted with a passphrase; downloaded backups are not encrypted, so
store them where only you and your company can access them.

## Credentials

- The local PostgreSQL passwords are random, created on first start and kept
  in `%LOCALAPPDATA%\TatumGames\tg_sales\postgres\credentials.json`.
- No API keys or secrets are in the source code, the web app or the release.
  Docker passwords go in `deploy/.env` (git-ignored).

## Contact data and compliance

Business contact details come only from your own entries and imports, the
store's published contact, or the official studio website, and each records
where it came from. Use them for legitimate business outreach and honor
opt-out requests (archive or delete the contact). tg_sales supports
exporting and deleting records; it does not by itself make anyone compliant
with GDPR or other laws.

## Before any network or hosted use

Sign-in, roles and HTTPS are required first (see
[DEPLOYMENT.md](DEPLOYMENT.md#5-future-hosting-for-a-team)). Do not publish the
port or bind the server to a network address.

## Reporting a vulnerability

Contact Tatum Games privately; do not open a public issue with details.
