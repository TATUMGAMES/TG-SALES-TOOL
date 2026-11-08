from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta, timezone

import pytest

from tg_sales.domain.ids import is_valid_id, new_id, stable_id, uuid7, uuid7_timestamp_ms
from tg_sales.domain.normalization import (
    domain_from_email,
    domain_from_url,
    normalize_email,
    normalize_name,
)
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.domain.time import UTC_TEXT_LENGTH, ensure_utc, format_utc, parse_utc, to_local

# --- identifiers -----------------------------------------------------------------


def test_uuid7_layout() -> None:
    value = uuid7(1_700_000_000_123)
    assert value.version == 7
    assert value.variant == uuid.RFC_4122
    assert uuid7_timestamp_ms(str(value)) == 1_700_000_000_123


def test_new_ids_are_unique_and_time_ordered_by_millisecond() -> None:
    ids = [new_id() for _ in range(2000)]
    assert len(set(ids)) == len(ids)
    assert all(is_valid_id(i) for i in ids)
    earlier, later = str(uuid7(1000)), str(uuid7(2000))
    assert earlier < later


def test_uuid7_rejects_out_of_range_timestamps() -> None:
    with pytest.raises(ValueError, match="range"):
        uuid7(-1)
    with pytest.raises(ValueError, match="range"):
        uuid7(1 << 48)


def test_stable_ids_are_deterministic_and_distinct() -> None:
    assert stable_id("pipeline_stage:won") == stable_id("pipeline_stage:won")
    assert stable_id("pipeline_stage:won") != stable_id("pipeline_stage:lost")
    assert uuid.UUID(stable_id("x")).version == 5


@pytest.mark.parametrize("value", ["", "not-a-uuid", "6F9619FF-8B86-D011-B42D-00C04FC964FF"])
def test_is_valid_id_rejects_non_canonical(value: str) -> None:
    assert not is_valid_id(value)


def test_uuid7_timestamp_rejects_other_versions() -> None:
    with pytest.raises(ValueError, match="UUIDv7"):
        uuid7_timestamp_ms(str(uuid.uuid4()))


# --- time ------------------------------------------------------------------------


def test_format_is_fixed_width_sortable_utc() -> None:
    plus_two = timezone(timedelta(hours=2))
    local = datetime(2026, 3, 29, 3, 30, tzinfo=plus_two)
    text = format_utc(local)
    assert text == "2026-03-29T01:30:00.000000Z"
    assert len(text) == UTC_TEXT_LENGTH
    assert parse_utc(text) == local
    assert parse_utc(text).tzinfo is UTC
    times = [datetime(2026, 1, d, tzinfo=UTC) for d in (3, 1, 2)]
    assert sorted(format_utc(t) for t in times) == [format_utc(t) for t in sorted(times)]


@pytest.mark.parametrize(
    "text", ["2026-01-01T00:00:00Z", "2026-01-01T00:00:00.000000+00:00", "garbage", ""]
)
def test_parse_utc_rejects_other_formats(text: str) -> None:
    with pytest.raises(ValueError, match="UTC timestamp"):
        parse_utc(text)


def test_naive_datetimes_are_rejected() -> None:
    with pytest.raises(ValueError, match="Naive"):
        ensure_utc(datetime(2026, 1, 1))  # noqa: DTZ001 - deliberately naive


def test_to_local_converts_for_display() -> None:
    zone = timezone(timedelta(hours=-8))
    assert to_local(datetime(2026, 1, 1, 8, tzinfo=UTC), zone).hour == 0


# --- normalization -----------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  Pixel-Forge   Studios, Inc. ", "pixel forge studios inc"),
        ("ÉCLAIR Games", "éclair games"),
        ("ｆｕｌｌ width", "full width"),  # noqa: RUF001 - full-width input is the point
        ("株式会社テスト", "株式会社テスト"),
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


def test_normalize_email() -> None:
    assert normalize_email("  Jane.Doe@Studio.Example ") == "jane.doe@studio.example"
    assert normalize_email("not an email") is None
    assert normalize_email(None) is None
    assert domain_from_email("x@Pub.Example") == "pub.example"
    assert domain_from_email("bad") is None


@pytest.mark.parametrize(
    ("url", "expected"),
    [
        ("https://www.Example.com/press", "example.com"),
        ("studio.example.org", "studio.example.org"),
        ("http://sub.example.net:8080/x?y", "sub.example.net"),
        ("", None),
        ("localhost", None),
        (None, None),
        ("http://[::1", None),
    ],
)
def test_domain_from_url(url: str | None, expected: str | None) -> None:
    assert domain_from_url(url) == expected


# --- default stages ----------------------------------------------------------------


def test_default_stages_cover_the_standard_pipeline() -> None:
    names = [s.name for s in DEFAULT_STAGES]
    assert names == [
        "Discovered",
        "Researching",
        "Contacted",
        "Follow-Up",
        "Interested",
        "Technical Review",
        "Negotiation",
        "Won",
        "Lost",
        "Not a Fit",
    ]
    assert len({s.id for s in DEFAULT_STAGES}) == len(DEFAULT_STAGES)
    assert [s.outcome.is_terminal for s in DEFAULT_STAGES].count(True) == 3
