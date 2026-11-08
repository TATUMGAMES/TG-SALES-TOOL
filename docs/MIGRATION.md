# Moving data from the desktop version (SQLite → PostgreSQL)

The earlier tg_sales desktop app stored everything in one SQLite file:
`%LOCALAPPDATA%\TatumGames\tg_sales\data\tg_sales.db`. The web version uses
PostgreSQL. The **desktop-data transfer** moves everything across.

## How to transfer

1. Close the desktop app.
2. Optional but recommended: copy `tg_sales.db` somewhere safe.
3. Start the web version (`launch.bat`), open **Settings & Sync › Desktop
   data**, choose `tg_sales.db`, keep **Trial run** on and run it. Nothing is
   saved; you see what would be transferred and any problems.
4. Turn the trial off and choose **Transfer now**. A backup of the PostgreSQL
   database is taken first.

From the command line (developers), the same code is in
`tg_sales.legacy.transfer.transfer()`.

## What happens

- **The original file is never changed.** It is copied with SQLite's online
  backup API, the copy's integrity is checked, and older desktop schemas
  (revisions 0001–0004) are upgraded **on the copy** to revision 0005.
- Every table is transferred in dependency order, in **one transaction**:
  any failure leaves PostgreSQL unchanged.
- **Preserved:** record ids, created/updated/deleted timestamps, creating
  device ids, prospects, contacts, games, opportunities and their stages,
  the complete activity ledger (stage history, outreach, corrections), tasks,
  playbook templates with revisions and outcomes, import history, discovery
  results, sync history and conflicts, snapshot metadata and shared settings.
- **Computer identity:** if the PostgreSQL database is new, it takes over the
  desktop installation's device id and current salesperson, so sync with
  colleagues and authorship continue unchanged. If it already has data, it
  keeps its own identity and the desktop's per-computer settings are skipped.
- **Default pipeline stages** that were never edited in the web version take
  the desktop names and order.
- **Repeatable:** rows already present with identical values are counted as
  "already here"; running the transfer again inserts nothing.
- **Never silent:** a row that already exists with different values is not
  overwritten but reported as a conflict; a row that cannot be read
  (malformed timestamp, JSON or value) or that refers to a missing record is
  reported with its table, id, column and original values, and records that
  depend on it are reported too.

## Verification

After the transfer, both databases are compared:

- for every table, the set of transferred ids and **every column value**
  (after the same normalization);
- activity counts per type;
- the ordered stage history of every opportunity.

Because KPIs and reports are calculated from these records with the same
code, identical records give identical numbers; the automated test
`tests/integration/test_legacy_transfer.py` also compares the full dashboard
before and after a transfer.

The report is saved as `legacy_transfer_<time>.json` and `.md` in the
`migration_reports` folder of the data folder, and shown in the app.

## Rollback and recovery

- The desktop file is untouched: you can keep using the desktop app or run
  the transfer again at any time.
- The web database was backed up just before the transfer (Settings & Sync ›
  Backups, reason "Pre-import"). Restoring it undoes the transfer completely.
- If something looks wrong, keep the transfer report and the log file
  (`%LOCALAPPDATA%\TatumGames\tg_sales\logs`) for your support contact.

## Notes

- Report folders, snapshots and the company logo from the desktop data folder
  can be copied with the transfer when it runs on the same computer (they are
  plain files); uploaded databases transfer records only. Copy the
  `reports`, `snapshots` and `assets` folders manually if you want them.
- This computer had no desktop data when the web version was built, so the
  transfer was verified with synthetic desktop databases at the current and
  first desktop schema revisions.
