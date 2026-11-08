# Importing prospect lists

tg_sales imports studios, publishers and data buyers, with their contacts and
games, from files you already have. Nothing is saved until you confirm the
last step, every import can be undone, and existing information is never
overwritten.

Start an import with **Import** in the header (Ctrl+I), or from the empty
Prospects page.

## Supported files

| Type | Details |
|------|---------|
| CSV (`.csv`) | Comma, semicolon, tab or vertical-bar separated; detected automatically |
| Excel workbook (`.xlsx`) | You choose the sheet when there are several |
| Text (`.txt`) | Tab/comma/semicolon separated columns, `Field: value` records separated by blank lines, or one value per line |

Text is read as UTF-8 (with or without a byte-order mark) or UTF-16 with a
byte-order mark. Other files are read as Windows-1252 and you are told to
check accented characters in the preview.

**Refused for safety or because they cannot be read reliably:** old `.xls`,
binary `.xlsb`, macro-enabled `.xlsm`/`.xltm` (also when renamed to `.xlsx`),
password-protected workbooks, damaged files, workbooks that expand to an
unsafe size, and text without a consistent structure. Each case explains
what to do instead (usually: save as `.xlsx` or CSV).

**Limits:** 50 MB per file, 100,000 rows, 200 columns, 10,000 characters per
cell. Files over 10 MB or 20,000 rows show a notice that reading will take a
moment.

**Formulas are never calculated.** A cell such as `=HYPERLINK(...)` is stored
as plain text and flagged; macros, links and file contents are never run.

## Steps

1. **Choose a file.** tg_sales checks its type and size and computes a
   fingerprint so it can tell you if the same file was imported before.
2. **Choose a sheet** (workbooks with several sheets only).
3. **Match columns.** Each column gets a suggestion from its name; you can
   change any of them or choose *Don't import*. Ambiguous names such as
   *Name*, *Title* or *Contact* are only filled in when the other columns or
   the values make the meaning clear. A column for the studio or company name
   is required. Choose how to read dates like `03/04/2027` (left empty and
   reported by default, or month-first / day-first).
4. **Preview rows.** Shows how each row was read, with errors (row skipped)
   and warnings (a value was ignored or left unknown).
5. **Review matches.** Rows that look like prospects you already have are
   listed with the reason. Choose *Create a new prospect*, *Add to* an
   existing one, or *Skip*. Rows that need a decision must be decided before
   you can continue; *Create new for all undecided* and *Skip all undecided*
   settle them at once.
6. **Confirm.** The exact number of prospects, contacts and games that will
   be created, updated or skipped is calculated with a trial run that saves
   nothing. You can export the list of problems as CSV.
7. **Import.** Everything is saved in one step. If anything fails, or you
   choose Cancel while it runs, nothing is saved.
8. **Result.** Shows what changed; you can export the problems or undo the
   import immediately.

## Recognized column names

Column names are matched without regard to case, spaces or punctuation.

| Imported as | Example column names |
|-------------|----------------------|
| Studio / company name | Studio, Company, Developer, Organization, Account, Team |
| Website | Website, URL, Site, Homepage, Domain |
| Company type | Type, Company type, Category, Segment |
| Location / Country | Location, City, Region, HQ / Country |
| Tags | Tags, Labels, Keywords (split on `,` `;` `\|`) |
| Company notes | Notes, Comments, Description |
| Contact name | Contact name, Full name, Person, Point of contact (or First name + Last name) |
| Contact role / title | Role, Job title, Position |
| Contact email | Email, E-mail, Email address, Business email |
| LinkedIn / X (Twitter) / other social URL | LinkedIn, Twitter, X, Socials |
| Contacted (yes / no) | Contacted, Reached out, Outreach, Emailed, Status |
| Game title / Release date / Platform / Store page | Game, Game title, Product / Release date, Launch / Platform / Steam URL, Store link |

## How values are interpreted

- **Contacted** accepts checkmarks (✓ ✔ ☑ ✅), `x`, yes/no, true/false, 1/0 and
  phrases such as *reached out* or *not contacted*. A blank cell stays
  *unknown*. Outreach status is **never** inferred from the presence of an
  email address, and an imported "yes" does not create a dated outreach
  activity (the date is not known), so it does not count towards dashboard
  outreach numbers.
- **Websites and social links** must be `http`/`https` addresses; `https://`
  is added when missing. Other schemes (for example `javascript:`) are ignored
  with a warning.
- **Emails** are lowercased and checked. One cell may hold several emails: if
  the name cell lists the same number of names separated by `;`, one contact
  is created per pair; otherwise the first email is used and the others are
  noted on the contact with a warning.
- **Release dates** accept `2027-03-14`, `14.03.2027`, `March 14, 2027`,
  `March 2027`, `Q3 2027`, `2027`, and words such as *TBA* or *Coming soon*
  (stored as unknown). Impossible dates are reported and left empty.
- **Blank rows** are ignored. **Rows without a studio name** are not imported
  and are listed as errors.

## Duplicates and updates

- Rows in the same file with the same website domain describe the same
  prospect; rows without a website join a row with the same name. Rows with
  the same name but **different websites stay separate**, because different
  studios can have similar names.
- A prospect you already have is matched automatically when it has the same
  website domain or a contact with the same email, or the same name and no
  conflicting website. Similar names, the same name with a different website,
  and several possible matches are always left for you to decide.
- Shared hosts (webmail such as gmail.com, social networks, `itch.io`, store
  pages) are never treated as a company's own website for matching.
- When a row is added to an existing prospect, only **empty** fields are
  filled in; new contacts, games and tags are added. Different values already
  on the prospect are kept and reported as warnings.

## Importing the same file again

Rows that were already imported are recognized and skipped, so importing a
file twice does not create duplicates. The confirm step tells you when the
same file was imported before.

## Undo

Open **Import history** on the Prospects page to see every import and undo
one. Undo removes the prospects, contacts and games the import added and
restores the details it filled in, in a single step. Records you changed after
the import, and prospects that have since gained opportunities, manually added
contacts or notes, are kept and counted in the result.

## What is stored

tg_sales stores the file name (without its folder), size, type, sheet and a
SHA-256 fingerprint, the column choices, the counts and error messages. The
file itself and its raw rows are not copied into the database. Imported
contacts record *Imported from <file name>* as their source.

## Example files

Synthetic example files for trying the importer are in
[`tests/fixtures/imports/`](../tests/fixtures/imports/): `sample_prospects.xlsx`
(two sheets), `messy_prospects.csv` (deliberately messy), `studios_tab.txt`,
`studios_key_value.txt` and `studios_cp1252.csv`. All names and domains in
them are invented.
