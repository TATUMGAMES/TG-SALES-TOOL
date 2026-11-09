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

from collections.abc import Callable
from datetime import UTC, datetime, timedelta

import pytest

from tg_sales.db.database import Database

START = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class FakeClock:
    """Deterministic clock; each reading advances by one millisecond."""

    def __init__(self, start: datetime = START) -> None:
        self.current = start

    def now(self) -> datetime:
        value = self.current
        self.current += timedelta(milliseconds=1)
        return value

    def set(self, value: datetime) -> None:
        self.current = value


@pytest.fixture
def clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def database(make_database: Callable[..., Database], clock: FakeClock) -> Database:
    return make_database(clock)
