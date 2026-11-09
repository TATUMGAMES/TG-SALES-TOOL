# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Sales lanes: user-defined business categories of opportunities.

A lane (for example "Consulting" or "Data licensing") groups opportunities by
what is being sold. It is not a pipeline stage: every lane moves through the
same stages ("Contacted", "Negotiation", "Won"…), and a stage may be limited
to one lane.

Each lane has a permanent ``key`` (stored on opportunities and stages) and a
display ``name`` that can change freely. The record id is derived from the
key, so the same lane created on two computers merges in sync.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from tg_sales.domain.ids import stable_id

MAX_KEY_LENGTH = 32
MAX_NAME_LENGTH = 80
MAX_DESCRIPTION_LENGTH = 500
COLOR_PATTERN = re.compile(r"^#[0-9a-f]{6}$")

# Lane colors offered in the interface (brand palette); any #rrggbb is accepted.
PALETTE: tuple[str, ...] = ("#a787bd", "#86c4c2", "#c7d47f", "#f6d271", "#d87b7a", "#8fa8d8")


def lane_id(key: str) -> str:
    """The record id of the lane with ``key`` (the same on every computer)."""
    return stable_id(f"sales_lane:{key}")


def key_from_name(name: str) -> str:
    """A lane key derived from a display name: ``"Enterprise Sales"`` → ``"enterprise_sales"``."""
    ascii_text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    key = re.sub(r"[^a-z0-9]+", "_", ascii_text.lower()).strip("_")
    return key[:MAX_KEY_LENGTH].rstrip("_") or "lane"


def label_for_key(key: str) -> str:
    """Readable fallback name for a lane key that has no lane record."""
    return key.replace("_", " ").strip().capitalize() or "Unknown lane"


def normalize_color(value: str | None) -> str | None:
    """``#RRGGBB`` in lower case, or None for empty; raises ValueError otherwise."""
    if value is None or not value.strip():
        return None
    color = value.strip().lower()
    if not COLOR_PATTERN.match(color):
        raise ValueError("colors are written as #rrggbb")
    return color


@dataclass(frozen=True)
class LanePreset:
    key: str
    name: str
    color: str
    description: str | None = None
    technical_handoff: bool = False

    @property
    def id(self) -> str:
        return lane_id(self.key)


# Lanes for a brand-new installation.
GENERIC_LANES: tuple[LanePreset, ...] = (
    LanePreset("general_sales", "General Sales", "#a787bd", "Direct sales to customers."),
    LanePreset("partnerships", "Partnerships", "#86c4c2", "Partners, resellers and alliances."),
    LanePreset("other", "Other", "#c7d47f", "Anything that does not fit another lane."),
)

# The lanes Tatum Games has always used. Kept on upgraded installations and
# offered as a preset; never added to a new installation automatically.
TATUM_GAMES_LANES: tuple[LanePreset, ...] = (
    LanePreset(
        "data_licensing",
        "Data licensing",
        "#86c4c2",
        "Licensing game-market data to buyers.",
        technical_handoff=True,
    ),
    LanePreset(
        "publisher_partnership",
        "Publisher partnership",
        "#a787bd",
        "Publishing and co-development partnerships with studios.",
    ),
    LanePreset(
        "mikros_marketing",
        "MIKROS Marketing",
        "#f6d271",
        "MIKROS Marketing services for studios.",
    ),
)

PRESETS: dict[str, tuple[LanePreset, ...]] = {
    "generic": GENERIC_LANES,
    "tatum_games": TATUM_GAMES_LANES,
}
PRESET_LABELS: dict[str, str] = {
    "generic": "General (General Sales, Partnerships, Other)",
    "tatum_games": "Tatum Games (Data licensing, Publisher partnership, MIKROS Marketing)",
}


@dataclass(frozen=True)
class LaneInfo:
    id: str
    key: str
    name: str
    description: str | None
    color: str | None
    sort_order: int
    technical_handoff: bool
    archived: bool
    opportunity_count: int = 0
    stage_count: int = 0

    @property
    def in_use(self) -> bool:
        return self.opportunity_count > 0 or self.stage_count > 0
