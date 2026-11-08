# Collaboration without a server (offline sync)

Each salesperson runs tg_sales on their own computer. To share work, you
exchange **change files** ("sync packages") through a company-approved channel
(company email, shared drive). There is no server and no cloud account.

## Using it

**Settings & Sync › Sync**

- **Export changes**: choose "Changes since my last export" (normal) or
  "Everything" (for a new colleague). Encryption is on by default: choose a
  passphrase of at least 10 characters and tell it to your colleague
  separately (by phone, not in the same email). The file downloads as
  `tg_sales_sync_<your-name>_<YYYYMMDDTHHMMSSZ>_<id>.zip`.
- Optionally prepare it for one colleague by entering their **sync ID**
  (Settings & Sync › Sync shows each computer's ID). Their tg_sales then warns
  anyone else who tries to import it.
- **Import changes**: choose the file, enter the passphrase, **Check
  package**. tg_sales shows who made it, when, how many records are new,
  updated or already up to date, possible duplicates, and any conflicts. Then
  **Import these changes**. A backup is made first; if anything goes wrong,
  nothing is changed.

## What travels

Prospects (organizations), contacts, games and their studio links, pipeline
stages, opportunities, tasks, the full activity history, playbook templates
with revisions and outcomes, salespeople's names, shared settings, and web
bookmarks from Resources.

What never travels: per-computer settings (theme, backups, discovery
settings, this computer's identity), local folder bookmarks, import history
and undo data, the discovery review queue, report files, snapshots, backups,
logs, passwords and credentials.

## How it stays correct

- **Every change is recorded** by the database itself (a trigger writes a
  change-log row with a change id for every insert and update of a shared
  record), so nothing can be missed, whichever part of the app made it.
- A package carries, for each changed record, its current values, its current
  change id and its full **history** of change ids. "Changes since my last
  export" uses the change-log position, not modification times.
- On import, each record is compared with yours:

  | Situation | Result |
  |-----------|--------|
  | You don't have it | Added (deleted records arrive as deleted) |
  | You already have this version or a newer one | Skipped |
  | Yours is an older version of theirs | Updated |
  | Both changed, identical values | Marked as the same, nothing to do |
  | **Both changed, different values** | **Conflict**: you choose, field by field, "Mine" or "Theirs" |
  | It refers to something you don't have yet | Kept waiting and added automatically when a later package brings it |
  | Activity events | Added once (identified by their id), never changed |

- A resolved conflict becomes a new version whose history includes both
  sides, so it reaches everyone without causing new conflicts. Each decision
  is kept in the conflict log.
- Importing the same package again changes nothing. Changes you received are
  forwarded when you export, so A → B → C → A works, and nothing loops.
- Possible duplicates (two different records for the same studio by website
  domain or name, or the same contact email) are **listed, not merged**.

## Safety

- Packages are checked before anything is read: only the expected file names
  (no folders, no `..`), size and compression limits (protection against ZIP
  bombs), SHA-256 of every file, supported format and the same database
  schema version, valid identifiers, types and values.
- Encryption: AES-256-GCM with a key derived from the passphrase (scrypt);
  the package's export id is bound to the encryption, so tampering or a wrong
  passphrase is detected. Without encryption, anyone who obtains the file can
  read its contents, including contact details.
- Packages exported from your own computer are refused on import.
- Everything is applied in one database transaction after a backup.

## Tested scenarios

`tests/integration/test_sync.py`: two computers converge; the same package
twice; concurrent edits produce a conflict and its resolution propagates;
identical edits converge; A → B → C → A without loops; tombstones and
archived stages; out-of-order packages; dashboards identical after merging;
encryption round trip, missing and wrong passphrase; malformed ZIP, path
traversal, absolute paths, huge compression ratio, unexpected files, damaged
manifest, newer format, checksum mismatch; schema mismatch; packages from the
same computer; invalid values; interrupted import rolls back; nothing new to
export; duplicate flagging; recipient warning. The browser workflow test also
exports and imports through the UI.
