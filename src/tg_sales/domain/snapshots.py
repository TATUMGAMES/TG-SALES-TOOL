"""Dashboard snapshot file names.

``dashboard_snapshot_YYYY-MM-DD_<epoch_ms>.png``: the local date for people,
plus the UTC epoch milliseconds so names sort by time and never collide (when
two snapshots share a millisecond, the next free millisecond is used).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from datetime import UTC, datetime, tzinfo

from tg_sales.domain.time import to_local

PREFIX = "dashboard_snapshot_"
NAME_PATTERN = re.compile(r"^dashboard_snapshot_\d{4}-\d{2}-\d{2}_\d{13,}\.png$")


def epoch_ms(moment: datetime) -> int:
    return int(moment.astimezone(UTC).timestamp() * 1000)


def snapshot_name(moment: datetime, zone: tzinfo | None = None, *, offset_ms: int = 0) -> str:
    day = to_local(moment, zone).date().isoformat()
    return f"{PREFIX}{day}_{epoch_ms(moment) + offset_ms}.png"


def unique_snapshot_name(
    moment: datetime, exists: Callable[[str], bool], zone: tzinfo | None = None
) -> str:
    offset = 0
    while exists(name := snapshot_name(moment, zone, offset_ms=offset)):
        offset += 1
    return name


def is_snapshot_name(name: str) -> bool:
    return bool(NAME_PATTERN.match(name))
