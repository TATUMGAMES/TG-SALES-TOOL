# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

from __future__ import annotations

from datetime import date

import pytest

from tg_sales.domain.periods import (
    PRESET_LABELS,
    DateRange,
    PeriodPreset,
    describe_range,
    preset_range,
    previous_range,
    subtract_months,
)

TODAY = date(2026, 10, 25)


@pytest.mark.parametrize(
    ("preset", "start", "days"),
    [
        (PeriodPreset.LAST_7_DAYS, date(2026, 10, 19), 7),
        (PeriodPreset.LAST_30_DAYS, date(2026, 9, 26), 30),
        (PeriodPreset.LAST_3_MONTHS, date(2026, 7, 26), 92),
        (PeriodPreset.LAST_6_MONTHS, date(2026, 4, 26), 183),
        (PeriodPreset.LAST_12_MONTHS, date(2025, 10, 26), 365),
    ],
)
def test_preset_ranges_end_today_inclusive(preset: PeriodPreset, start: date, days: int) -> None:
    result = preset_range(preset, TODAY)
    assert result == DateRange(start, TODAY)
    assert result.days == days
    assert result.contains(TODAY)
    assert not result.contains(date(2026, 10, 26))


def test_month_end_clamping() -> None:
    assert subtract_months(date(2026, 5, 31), 3) == date(2026, 2, 28)
    assert preset_range(PeriodPreset.LAST_3_MONTHS, date(2026, 5, 31)).start == date(2026, 3, 1)
    assert subtract_months(date(2028, 3, 31), 1) == date(2028, 2, 29)  # leap year
    assert subtract_months(date(2026, 1, 15), 12) == date(2025, 1, 15)


def test_custom_has_no_preset_dates() -> None:
    with pytest.raises(ValueError, match="custom"):
        preset_range(PeriodPreset.CUSTOM, TODAY)


def test_date_range_rejects_inverted_bounds() -> None:
    with pytest.raises(ValueError, match="after"):
        DateRange(date(2026, 2, 2), date(2026, 2, 1))
    assert DateRange(TODAY, TODAY).days == 1


def test_every_preset_has_a_label() -> None:
    assert set(PRESET_LABELS) == set(PeriodPreset)


@pytest.mark.parametrize(
    ("preset", "start", "end"),
    [
        (PeriodPreset.LAST_1_MONTH, date(2026, 9, 26), date(2026, 10, 25)),
        (PeriodPreset.PREVIOUS_MONTH, date(2026, 9, 1), date(2026, 9, 30)),
        (PeriodPreset.PREVIOUS_QUARTER, date(2026, 7, 1), date(2026, 9, 30)),
        (PeriodPreset.PREVIOUS_YEAR, date(2025, 1, 1), date(2025, 12, 31)),
    ],
)
def test_month_and_calendar_presets(preset: PeriodPreset, start: date, end: date) -> None:
    assert preset_range(preset, TODAY) == DateRange(start, end)


def test_calendar_presets_at_year_start() -> None:
    new_year = date(2027, 1, 3)
    assert preset_range(PeriodPreset.PREVIOUS_MONTH, new_year) == DateRange(
        date(2026, 12, 1), date(2026, 12, 31)
    )
    assert preset_range(PeriodPreset.PREVIOUS_QUARTER, new_year) == DateRange(
        date(2026, 10, 1), date(2026, 12, 31)
    )
    assert preset_range(PeriodPreset.LAST_1_MONTH, date(2026, 3, 31)).start == date(2026, 3, 1)


def test_previous_range_and_description() -> None:
    october = DateRange(date(2026, 10, 1), date(2026, 10, 31))
    assert previous_range(october) == DateRange(date(2026, 8, 31), date(2026, 9, 30))
    assert describe_range(october) == "2026-10-01 to 2026-10-31 (31 days, inclusive)"
    assert describe_range(DateRange(TODAY, TODAY)).endswith("(1 day, inclusive)")
