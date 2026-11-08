# Reports and dashboard snapshots

## Periods

All periods are inclusive local calendar days. A period starts at local
midnight on its first day and ends just before local midnight after its last
day (see [KPI_DICTIONARY.md](KPI_DICTIONARY.md) §1.2).

| Option | Days covered (example: today is 2026-10-25) |
|--------|---------------------------------------------|
| Last 7 days | today and the 6 days before (2026-10-19 to 2026-10-25) |
| Last 30 days | today and the 29 days before |
| Last month | the day after the same date one month ago, through today (2026-09-26 to 2026-10-25) |
| Last 3 / 6 / 12 months | the same rule with 3, 6 or 12 months; month ends are clamped |
| Previous calendar month | the whole month before this one (2026-09-01 to 2026-09-30) |
| Previous calendar quarter | the whole quarter before this one (2026-07-01 to 2026-09-30) |
| Previous calendar year | 2025-01-01 to 2025-12-31 |
| Custom range | any start and end date |

The Reports page shows the exact boundaries before you create a report. Each
report compares the period with the same number of days immediately before it.

## What a report contains

A report is a folder in the `reports` data folder:

| File | Contents |
|------|----------|
| `report.pdf` | A4 document with page numbers; major sections start on a new page |
| `report.html` | Optional self-contained preview for a web browser (charts embedded) |
| `data/*.csv` | One CSV per table, complete (the PDF shows at most 25 rows per list) |
| `manifest.json` | Period, filters, time generated, app version, page count and totals |

Sections: executive summary (with previous-period comparison), lead
acquisition, contacted and responded, opportunity stages (distribution at
period start and end, transitions, stage performance), wins and losses with
recorded reasons, activity by salesperson and product lane, follow-up backlog,
source effectiveness, trends (chart and data), notable progress, data quality
and caveats, and definitions.

## How numbers are defined

Reports use the same calculation as the dashboard, so for the same period and
filters every number matches the dashboard (this is tested). Each table names
the definition it follows, in brackets, which is a section of the
[KPI dictionary](KPI_DICTIONARY.md). Additional breakdowns used only in
reports:

- **Stage distribution at start** uses the stage-distribution method at the
  last moment before the period starts.
- **Stage transitions** count stage moves dated in the period between two
  different stages; a new opportunity counts as a move from "New" to its first
  stage.
- **Activity by salesperson and lane** counts logged events (after
  corrections) dated in the period, by the person who recorded them and the
  lane of the linked opportunity ("Not linked to an opportunity" otherwise).
- **Data quality** facts: corrections recorded in the period, events recorded
  more than a day after their entered date, opportunities without a
  salesperson, and events not linked to an opportunity.

When something cannot be calculated (for example a win rate with nothing won
or lost) the report says **Not available** rather than 0. "Notable progress"
lists recorded facts only (wins, proposals, technical handoffs and forward
stage moves); tg_sales does not write interpretations or conclusions.

## Dashboard snapshots

The **Snapshot** button on the Dashboard saves a PNG of either the visible
area or the whole dashboard (including parts scrolled out of view) with the
current filters. The browser renders the image from the dashboard's own page
content (never a screen capture, so other windows can never appear in it) at
two to three times the screen resolution, so it stays sharp on high-DPI
displays; the server checks and re-encodes the PNG before saving it.

Files are saved in the `snapshots` data folder as
`dashboard_snapshot_YYYY-MM-DD_<epoch_ms>.png`: the local date plus the UTC
time in milliseconds since 1970, which keeps names unique (if two snapshots
share a millisecond, the next free number is used). The period, filters, area,
time and app version are recorded with each snapshot. Snapshots are listed on
the Reports page, where they can be opened, downloaded and deleted.

## Opening, downloading and deleting

- **Open PDF / Open HTML preview** open the report in a new browser tab (the
  HTML preview is shown without scripts). **Show files** opens the report
  folder in Explorer when tg_sales runs on your own computer.
- **Download all** saves the report folder as a ZIP (PDF, HTML, CSV files and
  manifest); single CSV files can be opened from the list. Snapshots can be
  opened or downloaded. Downloads are saved by your browser and never replace
  a file you already have.
- **Delete** asks first and removes only files inside the tg_sales reports or
  snapshots folder. Report metadata (period, filters, totals) is also kept in
  the database (`report_records`).
- PDFs are produced with ReportLab (A4, page numbers, vector charts); charts
  in the HTML preview are SVG.
