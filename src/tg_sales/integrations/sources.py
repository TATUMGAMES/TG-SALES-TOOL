# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""The interface every game discovery source implements.

Sources are registered with a feature flag. Only sources whose terms and
technical access have been reviewed are enabled; others (for example mobile
app stores) stay disabled until an adapter exists, so they never appear as
unusable buttons.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Protocol

from tg_sales.cancellation import CancelToken
from tg_sales.domain.discovery import DiscoveryParams, SourceResult

ProgressCallback = Callable[[int, str], None]


class GameSourceAdapter(Protocol):
    name: str  # stable id stored with results, e.g. "steam"
    label: str  # shown to users
    attribution: str  # where the data comes from, shown next to results

    def discover(
        self,
        params: DiscoveryParams,
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> SourceResult:
        """Find candidate games for the windows in ``params``."""
        ...

    def lookup(
        self,
        references: Sequence[str],
        token: CancelToken | None = None,
        progress: ProgressCallback | None = None,
    ) -> SourceResult:
        """Fetch specific games from user-supplied links or ids."""
        ...

    def parse_reference(self, text: str) -> str | None:
        """The source's id for a link or id the user pasted, or None if not recognized."""
        ...


@dataclass(frozen=True)
class SourceInfo:
    name: str
    label: str
    enabled: bool
    note: str


# Feature flags: which sources exist and whether they are enabled.
SOURCES: tuple[SourceInfo, ...] = (
    SourceInfo(
        "steam",
        "Steam store",
        True,
        "Public Steam storefront data (store search, featured lists and app details).",
    ),
    SourceInfo(
        "google_play",
        "Google Play",
        False,
        "Not available: no adapter yet; requires a permitted data source.",
    ),
    SourceInfo(
        "app_store",
        "Apple App Store",
        False,
        "Not available: no adapter yet; requires a permitted data source.",
    ),
)
