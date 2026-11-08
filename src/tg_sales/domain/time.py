"""UTC timestamps: a single storage format, an injectable clock, local display.

All timestamps are stored and compared in UTC using a fixed-width text format
(``YYYY-MM-DDTHH:MM:SS.ffffffZ``) that sorts chronologically as plain text.
Naive datetimes are rejected so that local times can never be stored by
accident. Conversion to the user's local time happens only for display.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Protocol

UTC_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"
UTC_TEXT_LENGTH = len("2026-01-01T00:00:00.000000Z")


class Clock(Protocol):
    """Source of the current time (injected so tests are deterministic)."""

    def now(self) -> datetime: ...


class SystemClock:
    """The real UTC clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


def ensure_utc(value: datetime) -> datetime:
    """Return ``value`` converted to UTC; reject naive datetimes."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Naive datetime rejected: use a timezone-aware datetime (UTC).")
    return value.astimezone(UTC)


def format_utc(value: datetime) -> str:
    """Format a timezone-aware datetime as fixed-width UTC text."""
    return ensure_utc(value).strftime(UTC_FORMAT)


def parse_utc(text: str) -> datetime:
    """Parse fixed-width UTC text produced by :func:`format_utc`."""
    if len(text) != UTC_TEXT_LENGTH or not text.endswith("Z"):
        raise ValueError(f"not a tg_sales UTC timestamp: {text!r}")
    # fromisoformat is implemented in C and far faster than strptime for bulk reads.
    return datetime.fromisoformat(text).astimezone(UTC)


def to_local(value: datetime, zone: tzinfo | None = None) -> datetime:
    """Convert a UTC datetime to ``zone`` (default: the computer's local zone)."""
    return ensure_utc(value).astimezone(zone)
