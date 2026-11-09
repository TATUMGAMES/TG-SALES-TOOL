# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Reporting periods: preset trailing windows and validated custom ranges.

All ranges are inclusive calendar dates in the user's local time zone. A
trailing window ends on (and includes) the reference day:

* ``LAST_7_DAYS``: the reference day and the 6 days before it.
* ``LAST_30_DAYS``: the reference day and the 29 days before it.
* ``LAST_N_MONTHS`` (1, 3, 6, 12): from the day after the same calendar date
  N months earlier through the reference day (e.g. 3 months ending 2026-10-25
  starts 2026-07-26). Month ends are clamped (3 months ending 2026-05-31
  starts 2026-03-01).

Calendar presets cover the whole previous calendar month, quarter or year
before the reference day (e.g. on 2026-10-25: 2026-09-01 to 2026-09-30,
2026-07-01 to 2026-09-30, and 2025-01-01 to 2025-12-31).
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import StrEnum


class PeriodPreset(StrEnum):
    LAST_7_DAYS = "7d"
    LAST_30_DAYS = "30d"
    LAST_1_MONTH = "1m"
    LAST_3_MONTHS = "3m"
    LAST_6_MONTHS = "6m"
    LAST_12_MONTHS = "12m"
    PREVIOUS_MONTH = "prev_month"
    PREVIOUS_QUARTER = "prev_quarter"
    PREVIOUS_YEAR = "prev_year"
    CUSTOM = "custom"


PRESET_LABELS: dict[PeriodPreset, str] = {
    PeriodPreset.LAST_7_DAYS: "Last 7 days",
    PeriodPreset.LAST_30_DAYS: "Last 30 days",
    PeriodPreset.LAST_1_MONTH: "Last month",
    PeriodPreset.LAST_3_MONTHS: "Last 3 months",
    PeriodPreset.LAST_6_MONTHS: "Last 6 months",
    PeriodPreset.LAST_12_MONTHS: "Last 12 months",
    PeriodPreset.PREVIOUS_MONTH: "Previous calendar month",
    PeriodPreset.PREVIOUS_QUARTER: "Previous calendar quarter",
    PeriodPreset.PREVIOUS_YEAR: "Previous calendar year",
    PeriodPreset.CUSTOM: "Custom range",
}

_TRAILING_DAYS = {PeriodPreset.LAST_7_DAYS: 7, PeriodPreset.LAST_30_DAYS: 30}
_TRAILING_MONTHS = {
    PeriodPreset.LAST_1_MONTH: 1,
    PeriodPreset.LAST_3_MONTHS: 3,
    PeriodPreset.LAST_6_MONTHS: 6,
    PeriodPreset.LAST_12_MONTHS: 12,
}


@dataclass(frozen=True)
class DateRange:
    """An inclusive range of calendar dates."""

    start: date
    end: date

    def __post_init__(self) -> None:
        if self.start > self.end:
            raise ValueError(f"start {self.start} is after end {self.end}")

    @property
    def days(self) -> int:
        return (self.end - self.start).days + 1

    def contains(self, day: date) -> bool:
        return self.start <= day <= self.end


def subtract_months(day: date, months: int) -> date:
    """Return the same calendar date ``months`` earlier, clamped to month end."""
    month_index = day.year * 12 + (day.month - 1) - months
    year, month = divmod(month_index, 12)
    month += 1
    last_day = calendar.monthrange(year, month)[1]
    return date(year, month, min(day.day, last_day))


def preset_range(preset: PeriodPreset, today: date) -> DateRange:
    """Return the trailing range for a preset, ending on ``today`` inclusive."""
    if preset in _TRAILING_DAYS:
        return DateRange(today - timedelta(days=_TRAILING_DAYS[preset] - 1), today)
    if preset in _TRAILING_MONTHS:
        start = subtract_months(today, _TRAILING_MONTHS[preset]) + timedelta(days=1)
        return DateRange(start, today)
    if preset is PeriodPreset.PREVIOUS_MONTH:
        first_this_month = today.replace(day=1)
        last = first_this_month - timedelta(days=1)
        return DateRange(last.replace(day=1), last)
    if preset is PeriodPreset.PREVIOUS_QUARTER:
        quarter_start = date(today.year, 3 * ((today.month - 1) // 3) + 1, 1)
        last = quarter_start - timedelta(days=1)
        return DateRange(subtract_months(quarter_start, 3), last)
    if preset is PeriodPreset.PREVIOUS_YEAR:
        return DateRange(date(today.year - 1, 1, 1), date(today.year - 1, 12, 31))
    raise ValueError("A custom range has no preset dates; build a DateRange directly.")


def previous_range(dates: DateRange) -> DateRange:
    """The range of the same length that ends the day before ``dates`` starts."""
    end = dates.start - timedelta(days=1)
    return DateRange(end - timedelta(days=dates.days - 1), end)


def describe_range(dates: DateRange) -> str:
    """Plain-language boundaries, e.g. "2026-09-26 to 2026-10-25 (30 days, inclusive)"."""
    unit = "day" if dates.days == 1 else "days"
    return f"{dates.start.isoformat()} to {dates.end.isoformat()} ({dates.days} {unit}, inclusive)"
