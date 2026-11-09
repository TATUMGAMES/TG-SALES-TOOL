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

from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tg_sales.cancellation import CancelToken, OperationCancelledError
from tg_sales.domain.discovery import DiscoveryParams, GameType
from tg_sales.domain.enums import ReleasePrecision
from tg_sales.integrations.cache import JsonFileCache
from tg_sales.integrations.http import (
    AccessDeniedError,
    HttpClient,
    RateLimitedError,
    SourceUnavailableError,
    UnexpectedResponseError,
)
from tg_sales.integrations.steam import SteamStoreAdapter, app_ids_from_search
from tg_sales.integrations.website_contacts import (
    WebsiteContactFinder,
    candidate_pages,
    extract_addresses,
)

from .conftest import FakeClock
from .steam_fake import FakeSteam

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)


class Sleeps(list[float]):
    def __call__(self, seconds: float) -> None:
        self.append(seconds)


def client(
    transport: httpx.BaseTransport, sleeps: Sleeps | None = None, retries: int = 3
) -> HttpClient:
    return HttpClient(
        transport=transport,
        min_interval=0,
        max_retries=retries,
        sleep=sleeps if sleeps is not None else Sleeps(),
        jitter=lambda: 0.0,
    )


@pytest.fixture
def steam() -> FakeSteam:
    return FakeSteam()


@pytest.fixture
def adapter(steam: FakeSteam, tmp_path: Path) -> SteamStoreAdapter:
    return SteamStoreAdapter(
        client(steam.transport()), JsonFileCache(tmp_path / "cache"), FakeClock(NOW)
    )


# --- HTTP client ---------------------------------------------------------------------


def test_retries_429_with_retry_after_then_succeeds() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"Retry-After": "7"})
        return httpx.Response(200, json={"ok": True})

    sleeps = Sleeps()
    http = client(httpx.MockTransport(handler), sleeps)
    assert http.get_json("https://store.example/api") == {"ok": True}
    assert calls["n"] == 3
    assert sum(sleeps) == pytest.approx(14)  # Retry-After honored twice


def test_persistent_throttling_and_errors() -> None:
    http = client(httpx.MockTransport(lambda r: httpx.Response(429)), retries=2)
    with pytest.raises(RateLimitedError):
        http.get("https://store.example/x")
    with pytest.raises(UnexpectedResponseError, match="HTTP 503"):
        client(httpx.MockTransport(lambda r: httpx.Response(503)), retries=1).get(
            "https://store.example/x"
        )
    with pytest.raises(UnexpectedResponseError, match="could not read"):
        client(httpx.MockTransport(lambda r: httpx.Response(200, text="<html>"))).get_json(
            "https://store.example/x"
        )


def test_403_is_never_retried() -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(403)

    with pytest.raises(AccessDeniedError) as info:
        client(httpx.MockTransport(handler)).get("https://store.example/x")
    assert calls["n"] == 1
    assert "does not work around" in info.value.suggested_action


def test_network_failure_after_retries() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("timed out", request=request)

    sleeps = Sleeps()
    with pytest.raises(SourceUnavailableError, match="Could not reach"):
        client(httpx.MockTransport(handler), sleeps, retries=2).get("https://store.example/x")
    assert sum(sleeps) == pytest.approx(3.0)  # backoff 1 s then 2 s (no jitter in tests)


def test_cancellation_during_wait() -> None:
    token = CancelToken()

    def handler(request: httpx.Request) -> httpx.Response:
        token.cancel()
        return httpx.Response(500)

    with pytest.raises(OperationCancelledError):
        client(httpx.MockTransport(handler)).get("https://store.example/x", token=token)


def test_user_agent_identifies_the_app() -> None:
    seen: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.headers["User-Agent"])
        return httpx.Response(200, json={})

    client(httpx.MockTransport(handler)).get_json("https://store.example/x")
    assert seen[0].startswith("tg_sales/")


# --- Steam adapter ---------------------------------------------------------------------


def test_search_ids_come_from_image_urls_without_duplicates(steam: FakeSteam) -> None:
    assert app_ids_from_search(steam.data["search_comingsoon"]) == ["100001", "100004", "100006"]
    assert app_ids_from_search({"items": "nonsense"}) == []


def test_discover_normalizes_and_handles_demos_dlc_and_failures(
    adapter: SteamStoreAdapter, steam: FakeSteam
) -> None:
    result = adapter.discover(DiscoveryParams(max_candidates=20))
    by_id = {c.external_id: c for c in result.candidates}
    assert set(by_id) == {"100001", "100002", "100003", "100005", "100006"}  # demo → full game
    assert result.failed_ids == ("100007",)
    assert any("not a complete catalog" in n for n in result.notes)
    lantern = by_id["100001"]
    assert (
        lantern.release_date == date(2026, 11, 20)
        and lantern.release_precision is ReleasePrecision.DAY
    )
    assert lantern.self_published
    assert lantern.domain == "harborlight.example"
    assert lantern.support_email == "hello@harborlight.example"
    assert lantern.languages == ("English", "French", "Japanese")
    assert lantern.platforms == ("mac", "windows")
    orchard = by_id["100002"]
    assert orchard.release_date == date(2026, 7, 15)
    assert not orchard.self_published and len(orchard.publishers) == 2
    assert orchard.support_email is None
    dlc = by_id["100003"]
    assert dlc.game_type is GameType.DLC and dlc.parent_external_id == "100002"
    echo = by_id["100005"]
    assert echo.release_date is None and echo.release_precision is ReleasePrecision.UNKNOWN
    assert echo.release_text == "To be announced"
    starfall = by_id["100006"]
    assert starfall.release_precision is ReleasePrecision.QUARTER
    assert steam.details_requests().count("100001") == 1  # duplicate listing fetched once


def test_details_are_cached_and_stale_copies_are_marked(steam: FakeSteam, tmp_path: Path) -> None:
    clock = FakeClock(NOW)
    adapter = SteamStoreAdapter(client(steam.transport()), JsonFileCache(tmp_path / "c"), clock)
    adapter.lookup(["https://store.steampowered.com/app/100001/Lantern_Tides/"])
    adapter.lookup(["100001"])
    assert steam.details_requests() == ["100001"]  # second lookup served from cache
    clock.set(NOW + timedelta(days=2))  # cache expired, and Steam is unreachable
    steam.offline = True
    result = adapter.lookup(["100001"])
    (candidate,) = result.candidates
    assert candidate.stale and candidate.fetched_at < NOW + timedelta(seconds=1)
    assert result.stale_count == 1 and any("not current" in n for n in result.notes)
    assert adapter.lookup(["999999"]).failed_ids == ("999999",)


def test_throttling_stops_further_requests_in_the_run(steam: FakeSteam, tmp_path: Path) -> None:
    def throttle(request: httpx.Request) -> httpx.Response | None:
        if request.url.path == "/api/appdetails":
            return httpx.Response(429)
        return None

    steam.override = throttle
    adapter = SteamStoreAdapter(
        client(steam.transport(), retries=1), JsonFileCache(tmp_path / "c"), FakeClock(NOW)
    )
    result = adapter.lookup(["100001", "100002", "100005"])
    assert result.candidates == ()
    assert len(steam.details_requests()) == 2  # one id with one retry, then the run stopped asking
    assert any("slow down" in n for n in result.notes)


def test_offline_search_raises(steam: FakeSteam, adapter: SteamStoreAdapter) -> None:
    steam.offline = True
    with pytest.raises(SourceUnavailableError):
        adapter.discover(DiscoveryParams(max_candidates=5))


def test_parse_reference(adapter: SteamStoreAdapter) -> None:
    assert adapter.parse_reference("413150") == "413150"
    assert (
        adapter.parse_reference("https://store.steampowered.com/app/413150/Stardew_Valley/")
        == "413150"
    )
    assert adapter.parse_reference("https://example.com/app/1") is None
    assert adapter.parse_reference("not a link") is None


# --- website contacts ------------------------------------------------------------------

HOME = """<html><body><a href="/press">Press kit</a> <a href="https://other.example/contact">x</a>
<a href="/blog">Blog</a><a href="mailto:Business@HarborLight.example?subject=Hi">Mail us</a>
<p>Fan mail: noreply@harborlight.example</p><img src="logo@2x.png"></body></html>"""
PRESS = "<html><body>Press: press@harborlight.example, also team@freemail.example</body></html>"


def site(robots: str = "User-agent: *\nAllow: /\n") -> httpx.MockTransport:
    pages = {"/robots.txt": robots, "/": HOME, "/press": PRESS}

    def handler(request: httpx.Request) -> httpx.Response:
        body = pages.get(request.url.path)
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    return httpx.MockTransport(handler)


def test_extraction_helpers() -> None:
    assert extract_addresses(HOME) == ["business@harborlight.example"]
    assert candidate_pages(HOME, "https://harborlight.example") == [
        "https://harborlight.example/press"
    ]


def test_finder_reads_home_and_contact_pages() -> None:
    result = WebsiteContactFinder(client(site())).find("https://harborlight.example")
    emails = [(a.email, a.source_url) for a in result.addresses]
    assert emails == [
        ("business@harborlight.example", "https://harborlight.example"),
        ("press@harborlight.example", "https://harborlight.example/press"),
        ("team@freemail.example", "https://harborlight.example/press"),
    ]
    assert result.checked_urls == (
        "https://harborlight.example",
        "https://harborlight.example/press",
    )


def test_finder_respects_robots_and_reports_nothing_found() -> None:
    blocked = WebsiteContactFinder(client(site("User-agent: *\nDisallow: /\n"))).find(
        "https://harborlight.example"
    )
    assert blocked.blocked_by_robots and blocked.addresses == ()

    def empty(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/robots.txt":
            return httpx.Response(404)
        return httpx.Response(
            200, text="<html>No addresses here</html>", headers={"content-type": "text/html"}
        )

    nothing = WebsiteContactFinder(client(httpx.MockTransport(empty))).find(
        "https://quietowl.example"
    )
    assert nothing.addresses == () and "No business email" in nothing.message
    invalid = WebsiteContactFinder(client(httpx.MockTransport(empty))).find("javascript:alert(1)")
    assert "not valid" in invalid.message
