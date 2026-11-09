# Importing prospect lists

tg_sales imports companies (studios, publishers, customers, partners…), with
their contacts and games, from files you already have. Nothing is saved until
you confirm the last step, and every import can be undone. By default existing
information is never overwritten; you can explicitly choose to replace
existing values for one import (see [Duplicates and updates](#duplicates-and-updates)).

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
   change any of them or choose *Don't import*. The list is grouped into
   *Standard fields* and your *Custom fields*, and ends with
   **+ Create custom field…** (see [Custom fields](#custom-fields)). Ambiguous
   names such as *Name*, *Title* or *Contact* are only filled in when the
   other columns or the values make the meaning clear. A column for the
   company name is required. Each field can be chosen for one column only
   (except tags, notes and social links); a column chosen twice is marked in
   red. When the example values do not look like the chosen field's type (a
   date, a web address, a number, yes/no) the column shows a warning before
   you continue. Choose how to read dates like `03/04/2027` (left empty and
   reported by default, or month-first / day-first), and whether to
   [replace existing values](#duplicates-and-updates).
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
8. **Result.** Shows **rows imported**, **rows skipped** (already present,
   chosen to skip, or nothing new), **rows failed** (with the reason for each
   row), warnings, and the prospects, contacts and games created or updated.
   You can export the problems or undo the import immediately.

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
| **Review date** | Reviewed On, Review Date, Last Reviewed, Date Reviewed, Reviewed Date, Last Review |
| **Qualification source URL** | Qualification Source URL, Qualification Source, Source URL, Research URL, Reference URL, Qualification Link, Source Link |
| A custom field | The custom field's name, e.g. *Account Tier* for a field called "Account tier" |

A column called just *Source* is **not** suggested as the qualification
source URL: it usually holds a lead-source category such as *Referral* or
*LinkedIn*. Map it to a custom text field if you want to keep it.

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
- **Review date** is when the prospect was last reviewed or qualified (not
  when it was created, updated, contacted or due for a follow-up). It accepts
  full dates such as `2026-03-14`, `14/03/2026`, `03/14/2026`,
  `March 14, 2026` or a date cell in Excel, and is stored as a date. Dates
  that could be day/month or month/day (`04/03/2026`) are left empty and
  reported unless you choose the date order; a month, quarter or year alone
  is reported and left empty.
- **Qualification source URL** is the page where you found or qualified the
  prospect (a research list, a company profile, a search result). It is
  stored **exactly as written**, including the query string and `#fragment`,
  for example
  `https://research.example/lists?segment=indie&page=3#entry-12`. It must be
  an `http`/`https` address without a password in it; anything else is
  reported and left empty. tg_sales never opens or downloads the address; on
  the prospect it is a link that opens in a new browser tab.
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
  filled in (including review date, qualification source URL and custom
  fields); new contacts, games and tags are added. Different values already
  on the prospect are kept and reported as warnings ("Kept the existing review
  date; the file has a different value").
- **Replace existing values** (a switch on the column step, off by default):
  the file's value replaces a different existing value for the website,
  company type, location, country, review date, qualification source URL,
  contact job title, game platform, store page and release date, and custom
  fields. Names, notes, tags and outreach status are never replaced. The
  result shows how many values were replaced, and **Undo** restores them.

## Custom fields

Use a custom field when your file has information the standard fields do not
cover, such as *Account Tier*, *Industry Subcategory*, *Annual Revenue
Estimate*, *Internal Research Notes* or *Partnership Category*.

1. On the column step, open the column's list and choose
   **+ Create custom field…** (or create fields in **Settings › Custom
   fields**).
2. Enter the field name (the column name is filled in), choose the type —
   **Text**, **Number**, **Date**, **Web address (URL)** or **Yes / no** —
   and whether it belongs to **Prospects** or **Contacts**.
3. The new field is selected for that column, and is offered (and suggested
   by name) in every later import.

Values are checked against the type: `$1,250,000` becomes the number
1250000, `yes`/`no`/✓ become yes or no, dates are read like review dates and
web addresses are kept exactly. A value that does not fit is reported for
that row and left empty; the rest of the row is still imported. Contact
fields are filled for the row's contact, so the row needs a contact name,
email or social link.

Custom fields appear on the prospect (and on each contact), can be edited
there, are included as extra columns in **Export CSV** on the Prospects page,
and keep their values when the record is edited or imported again. Renaming
a field keeps its values; its type cannot change. Archiving a field hides it
from forms, imports and exports but keeps every value; restoring it brings
them back.

## Correcting import errors

- **"No studio or company name"**: the row has no value in the company name
  column. Fill it in, or check that the right column is chosen.
- **"… not recognized; left empty"** or **"Not a valid web address"**: correct
  the cell in your file and import it again (unchanged rows are skipped), or
  edit the prospect afterwards.
- **"Only one column can be mapped to …"**: two columns were given the same
  field. Choose another field for one of them, or *Don't import*.
- **A field is missing from the list**: choose **+ Create custom field…**. An
  archived custom field is not offered; restore it in Settings › Custom
  fields.
- Use **Export problems as CSV** for a spreadsheet of every problem with the
  original row values next to it.

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
