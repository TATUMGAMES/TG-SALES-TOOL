# tg_sales KPI Dictionary

This dictionary defines every sales metric shown in tg_sales dashboards and
reports: what is counted, the time it is attributed to, the denominator for
rates, and the equivalent SQL. Dashboards and reports must use these
definitions so that the same period and filters always give the same numbers.

Each metric has a **status**: *Implemented* (calculated by the application and
covered by tests) or *Defined* (definition agreed; calculation not yet built).
A test (`tests/unit/test_kpi_dictionary.py`) checks that every metric below is
implemented and that the dashboard's metric names match these headings.

## 1. Conventions used by every metric

### 1.1 Source of truth

- History comes from the immutable **activity ledger** (`activities`) and from
  record creation and deletion times. Current values on a record (for example
  an opportunity's `stage_id`) are never used to answer questions about the
  past.
- **Corrections** are applied before counting: an event voided by a
  correction is ignored, and an event moved by a correction counts at its
  corrected time. When several corrections target one event, the most recently
  recorded one wins.
- Saved dashboard snapshots are pictures for sharing, not a data source.

### 1.2 Time and periods

- An event belongs to a period by when it **happened** (`occurred_at_utc`),
  not when it was recorded. Backdated and imported historical events
  therefore count in the period in which they happened.
- Periods are defined in the user's **local time zone** as whole calendar
  days. A period from local date *S* to local date *E* (inclusive) covers the
  half-open UTC interval `[local midnight of S, local midnight of E+1)`.
  Converting each boundary separately handles daylight-saving changes
  correctly (a period may contain a 23- or 25-hour day).
- Preset periods are trailing windows ending today, inclusive: last 7 days,
  last 30 days, last 3/6/12 months (from the day after the same date N months
  earlier; month ends are clamped).
- "As of" questions use an exact moment `T` and include everything that
  happened at or before `T`. "At the end of the period" means the last moment
  before `P1` (`T = P1 − 1 µs`), so an event at exactly the next local midnight
  belongs to the next period.
- Ties between events at the same moment are broken by recorded time and then
  by event id, so results are deterministic.

### 1.3 Records, deletion and duplicates

- Records deleted (tombstoned) at or before the end of the period are
  excluded. A record deleted after the period still counts in that period.
- Each event is counted once (events are unique by `id`; sync never imports
  an event twice).
- "Unique" counts use distinct ids (for example distinct `contact_id`).

### 1.4 Attribution and filters

- **Salesperson filter:** activity metrics use the event's `actor_id` (who did
  it). Opportunity metrics use the opportunity's current `owner_actor_id`;
  ownership history is not tracked, so reassigning an owner moves that
  opportunity's history to the new owner.
- **Product lane filter:** uses the opportunity's `product_lane`. Activities
  without an opportunity are included only when no lane filter is set.
- **Leads added** and **lead-source quality** use the salesperson who created
  the organization (the actor of its `organization_created` event); the lane
  filter does not apply to them and the card says "(all product lanes)".
  **Contacts added** is not filtered (contacts carry no salesperson or lane).

### 1.5 Zero versus not available

- A count with nothing to count is `0`.
- A rate whose denominator is zero is **not available** (shown as "Not
  available"), never `0%`.
- A duration with no qualifying transitions is **not available**.

## 2. Metrics

Notation: `[P0, P1)` is the period in UTC; `T` is an as-of moment;
`live(x, P1)` means `x.deleted_at_utc IS NULL OR x.deleted_at_utc >= P1`;
`effective(a)` means activity `a` after corrections are applied.

### Pipeline stage distribution (as of a moment)

**Status:** Implemented (`services/pipeline_history.py`, tested in
`tests/integration/test_ledger_history.py` and `tests/unit/test_domain_pipeline.py`).

The number of opportunities in each stage at moment `T`. Each opportunity's
stage is the target of its latest effective `opportunity_created` or
`stage_change` event with `occurred_at_utc <= T`. Opportunities with no such
event did not exist yet. Opportunities deleted at or before `T` are excluded.

```sql
-- Conceptually (corrections applied first):
WITH placed AS (
  SELECT a.opportunity_id,
         CASE a.type WHEN 'stage_change' THEN json_extract(a.payload, '$.to_stage_id')
                     ELSE json_extract(a.payload, '$.stage_id') END AS stage_id,
         ROW_NUMBER() OVER (PARTITION BY a.opportunity_id
                            ORDER BY a.occurred_at_utc DESC, a.created_at_utc DESC, a.id DESC) AS rn
  FROM activities a
  WHERE a.type IN ('opportunity_created', 'stage_change') AND a.occurred_at_utc <= :T
)
SELECT p.stage_id, COUNT(*)
FROM placed p JOIN opportunities o ON o.id = p.opportunity_id
WHERE p.rn = 1 AND (o.deleted_at_utc IS NULL OR o.deleted_at_utc > :T)
GROUP BY p.stage_id;
```

Example: an opportunity created in Discovered on 1 September and moved to
Contacted on 4 September counts in Discovered as of 3 September and in
Contacted as of 5 September, whatever its stage is today.

### Leads added

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

Organizations created in the period. Contacts added are reported separately.

```sql
SELECT COUNT(*) FROM organizations o
WHERE o.created_at_utc >= :P0 AND o.created_at_utc < :P1 AND live(o, :P1);
```

### Contacts added

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

```sql
SELECT COUNT(*) FROM contacts c
WHERE c.created_at_utc >= :P0 AND c.created_at_utc < :P1 AND live(c, :P1);
```

### Unique contacts attempted

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

Distinct contacts with at least one effective outreach event in the period.
Outreach event types: `contacted`, `email`, `linkedin_invite`,
`linkedin_message`, `phone_call`. Having an email address is never treated as
an attempt. A "contacted" flag imported from a spreadsheet sets the contact's
outreach status but creates no outreach event (its date is unknown), so it is
not counted here. Logged interactions are counted by the date the salesperson
entered (`occurred_at_utc`); voided entries are excluded by `effective(a)`.
`task_created`, `task_completed`, technical handoff drafts and notes are not
outreach events.

```sql
SELECT COUNT(DISTINCT a.contact_id) FROM activities a
WHERE effective(a) AND a.contact_id IS NOT NULL
  AND a.type IN ('contacted','email','linkedin_invite','linkedin_message','phone_call')
  AND a.occurred_at_utc >= :P0 AND a.occurred_at_utc < :P1;
```

### Replies

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

Effective `reply` events in the period (each reply counts once).

```sql
SELECT COUNT(*) FROM activities a
WHERE effective(a) AND a.type = 'reply'
  AND a.occurred_at_utc >= :P0 AND a.occurred_at_utc < :P1;
```

### Active conversations / active opportunities

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

Opportunities whose stage at the end of the period (`T = P1 − 1 µs`) is a
non-terminal stage (`outcome = 'open'`), computed with the stage-distribution
method above. Opportunities deleted at or before `P1` are excluded.

### Technical handoffs and proposals

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

Effective `technical_handoff` (respectively `proposal`) events in the period.

### Won and lost

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

Opportunities whose **last** effective stage-placing event in the period moved
them into a stage with outcome `won` (respectively `lost`), using the event's
`payload.to_outcome` (or, for older events without it, the stage's outcome). An
opportunity reopened and closed again in the same period is counted once, by
its last transition; one reopened and still open at the end of the period is
not counted. Opportunities deleted at or before `P1` are excluded.

### Win rate

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

`won / (won + lost)` for opportunities closed in the period. `not_a_fit`
closures are excluded from both numerator and denominator. **Not available**
when `won + lost = 0`.

### Follow-ups due and overdue

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

For live opportunities in non-terminal stages with `next_action_at_utc` set:
*due* = `next_action_at_utc` within the period; *overdue* =
`next_action_at_utc < now`. This is a current-state metric (follow-up dates are
not historical) and is labeled as such.

### Median time in stage

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

For each stage, the median duration between an effective event placing an
opportunity in the stage and the next effective event moving it out, over
exits that happened in the period. Stays still in progress are not counted.
**Not available** when there are no exits.

### Stage conversion rate

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

For stage *S*: opportunities that left *S* for a later stage (higher
`sort_order`) during the period, divided by all opportunities that left *S*
during the period. **Not available** when no opportunity left *S*.

### Lead-source quality

**Status:** Implemented (`domain/kpi.py`, `services/kpis.py`; tested in `tests/integration/test_kpis.py`).

Per organization `source` (`manual`, `import`, `discovery`, `sync`): leads
added in the period, and the share of those leads with at least one
opportunity that, by the end of the period, reached an open stage beyond the
first open stage (by `sort_order`; Discovered by default) or a `won` outcome.
**Not available** for a source with no leads.

### Trends

**Status:** Implemented (`domain/kpi.py`).

Leads added, replies, won and lost per bucket of the period: days for periods
up to 31 days, 7-day weeks (starting on the period's first day) up to 190 days,
otherwise calendar months. Bucket boundaries are local midnights. Each series
sums exactly to the matching card for the same period and filters.

### Funnel

**Status:** Implemented (`domain/kpi.py`).

For opportunities created in the period (the cohort), the number that reached
at least each open stage (by `sort_order`) by the end of the period, plus the
number won. A won opportunity counts as having passed every open stage.

### Report-only breakdowns

**Status:** Implemented (`domain/kpi.py`; used by reports, see
[REPORTS.md](REPORTS.md); tested in `tests/integration/test_reports.py`).

- *Stage distribution at period start*: the stage-distribution method at
  `T = P0 − 1 µs`.
- *Stage transitions*: per opportunity, consecutive effective stage-placing
  events where the later one is dated in `[P0, P1)` and the stages differ;
  an `opportunity_created` event dated in the period counts as a move from
  "New".
- *Activity by salesperson and lane*: effective non-stage events dated in the
  period, grouped by `actor_id`, the product lane of the linked opportunity
  (none when not linked) and type, with the report's filters applied.
- *Data quality*: corrections recorded in the period; events in the period
  whose `created_at_utc` is more than one day after `occurred_at_utc`; visible
  opportunities without an owner; events in the period without an
  opportunity.

### Release windows

**Status:** Implemented (`services/kpis.py`).

Games linked to live prospects with a known release date, counted per calendar
month from two months before the current month to five months after. This is
current data (release dates are not historical) and is labeled as such.
