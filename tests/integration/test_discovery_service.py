from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest

from tg_sales.db.database import Database
from tg_sales.domain.discovery import (
    ContactStatus,
    CrmState,
    DiscoveryFilters,
    DiscoveryParams,
    DiscoveryWindow,
    LeadStatus,
    ScoringRules,
    Timing,
)
from tg_sales.domain.enums import RecordSource
from tg_sales.domain.prospects import OrganizationDraft, ProspectQuery
from tg_sales.integrations.cache import JsonFileCache
from tg_sales.integrations.http import HttpClient
from tg_sales.integrations.steam import SteamStoreAdapter
from tg_sales.integrations.website_contacts import WebsiteContactFinder
from tg_sales.services.discovery import DiscoveryError, DiscoveryService
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.prospects import ProspectService

from .conftest import FakeClock
from .steam_fake import FakeSteam

pytestmark = pytest.mark.integration

NOW = datetime(2026, 10, 1, 12, tzinfo=UTC)
ALL = DiscoveryFilters(timings=frozenset(Timing), statuses=frozenset(LeadStatus), include_dlc=True)


def http(transport: httpx.BaseTransport) -> HttpClient:
    return HttpClient(transport=transport, min_interval=0, max_retries=1, sleep=lambda _s: None)


class Setup:
    def __init__(self, database: Database, clock: FakeClock, tmp_path: Path) -> None:
        clock.set(NOW)
        self.clock = clock
        self.steam = FakeSteam()
        self.actor = ensure_local_actor(database)
        adapter = SteamStoreAdapter(
            http(self.steam.transport()), JsonFileCache(tmp_path / "cache"), clock
        )
        self.site_pages: dict[str, str] = {}
        site = httpx.MockTransport(self._site)
        self.service = DiscoveryService(
            database, self.actor, {"steam": adapter}, WebsiteContactFinder(http(site)), zone=UTC
        )
        self.prospects = ProspectService(database, self.actor)

    def _site(self, request: httpx.Request) -> httpx.Response:
        body = self.site_pages.get(f"{request.url.host}{request.url.path}")
        if body is None:
            return httpx.Response(404)
        return httpx.Response(200, text=body, headers={"content-type": "text/html"})

    def views(  # type: ignore[no-untyped-def]
        self, filters: DiscoveryFilters = ALL, params: DiscoveryParams | None = None
    ):
        return {
            v.candidate.external_id: v
            for v in self.service.leads(params or DiscoveryParams(), filters)
        }


@pytest.fixture
def setup(database: Database, clock: FakeClock, tmp_path: Path) -> Setup:
    return Setup(database, clock, tmp_path)


def test_run_builds_review_queue_with_timing_scores_and_contacts(setup: Setup) -> None:
    outcome = setup.service.run(DiscoveryParams(max_candidates=20))
    assert outcome.succeeded and outcome.found == 5 and outcome.new == 5
    views = setup.views()
    lantern, orchard, echo, starfall = (
        views["100001"],
        views["100002"],
        views["100005"],
        views["100006"],
    )
    assert lantern.timing is Timing.UPCOMING
    assert orchard.timing is Timing.RECENT
    assert echo.timing is Timing.UNKNOWN_DATE
    assert starfall.timing is Timing.OUTSIDE  # Q1 2027 is beyond 90 days from 1 Oct 2026
    assert lantern.contact.status is ContactStatus.NEEDS_VERIFICATION
    assert lantern.contact.email == "hello@harborlight.example"
    assert "store page" in lantern.contact.source_label
    assert orchard.contact.status is ContactStatus.NOT_FOUND and orchard.contact.email is None
    reasons = [r.text for r in lantern.score.reasons]
    assert "Releases within the upcoming window" in reasons
    assert "Self-published (no separate publisher listed)" in reasons
    assert "Public business contact found" in reasons
    assert lantern.score.total == 70 and lantern.score.confidence == "high"
    assert echo.score.confidence == "medium"  # no announced date
    assert views["100003"].score.total < orchard.score.total  # DLC penalty
    run = setup.service.last_run()
    assert run is not None and run.status == "completed" and run.found == 5


def test_default_filters_and_custom_rules(setup: Setup) -> None:
    setup.service.run(DiscoveryParams(max_candidates=20))
    default = setup.views(DiscoveryFilters())
    assert set(default) == {"100001", "100002", "100005"}  # DLC and out-of-window hidden
    windows = DiscoveryParams(window=DiscoveryWindow(upcoming_days=200, recent_days=30))
    wide = setup.views(DiscoveryFilters(), windows)
    assert set(wide) == {"100001", "100005", "100006"}  # July release now outside 30 days
    linux = setup.views(DiscoveryFilters(platform="linux"))
    assert set(linux) == {"100005"}
    assert set(setup.views(DiscoveryFilters(self_published_only=True))) == {"100001", "100005"}
    assert set(setup.views(DiscoveryFilters(language="japanese"))) == {"100001"}
    assert set(setup.views(DiscoveryFilters(genre="Strategy"))) == {"100002"}
    rules = DiscoveryParams(rules=ScoringRules(target_genres=("Action",)))
    echo = setup.views(params=rules)["100005"]
    assert any(r.text == "Target genre: Action" for r in echo.score.reasons)


def test_rerun_keeps_review_status_and_found_contacts(setup: Setup) -> None:
    setup.service.run(DiscoveryParams(max_candidates=20))
    views = setup.views()
    setup.service.set_status(views["100002"].id, LeadStatus.DISMISSED)
    setup.service.set_contact(
        views["100002"].id, "Deals@Copperleaf.example", "https://copperleaf.example/contact"
    )
    setup.service.mark_contact_verified(views["100002"].id)
    setup.clock.set(NOW + timedelta(days=2))
    outcome = setup.service.run(DiscoveryParams(max_candidates=20))
    assert outcome.new == 0
    orchard = setup.views()["100002"]
    assert orchard.status is LeadStatus.DISMISSED
    assert orchard.contact.status is ContactStatus.VERIFIED_SOURCE
    assert orchard.contact.email == "deals@copperleaf.example"
    assert "copperleaf.example/contact" in orchard.contact.source_label
    assert "100002" not in setup.views(DiscoveryFilters())  # dismissed are hidden by default
    with pytest.raises(DiscoveryError):
        setup.service.set_contact(orchard.id, "not-an-email", "x")


def test_outdated_results_are_never_shown_as_current(setup: Setup) -> None:
    setup.service.run(DiscoveryParams(max_candidates=20))
    assert not setup.views()["100001"].outdated
    setup.clock.set(NOW + timedelta(days=3))
    assert setup.views()["100001"].outdated  # not refreshed within a day
    setup.steam.offline = True
    outcome = setup.service.run(DiscoveryParams(max_candidates=20))
    assert not outcome.succeeded and "Could not reach" in (outcome.error or "")
    assert setup.views()["100001"].outdated  # the saved list remains, marked outdated
    run = setup.service.last_run()
    assert run is not None and run.status == "failed"
    stale = setup.service.lookup(["100001"])  # details come from cache when Steam is unreachable
    assert stale.succeeded and any("not current" in n for n in stale.notes)
    assert setup.views()["100001"].outdated


def test_lookup_from_pasted_links(setup: Setup) -> None:
    outcome = setup.service.lookup(
        ["https://store.steampowered.com/app/100006/Starfall_Ledger/", "garbage", "100006"]
    )
    assert outcome.found == 1
    with pytest.raises(DiscoveryError, match="Steam store links"):
        setup.service.lookup(["garbage only"])


def test_crm_duplicate_states_and_saving(setup: Setup) -> None:
    renamed = setup.prospects.create(
        OrganizationDraft("Old Forge Games", "https://novaforge.example")
    )
    setup.prospects.create(OrganizationDraft("Quiet Owl"))
    setup.service.run(DiscoveryParams(max_candidates=20))
    views = setup.views()
    assert views["100006"].crm_state is CrmState.STUDIO_IN_CRM  # renamed studio, same domain
    assert views["100006"].crm_organization_id == renamed
    assert views["100005"].crm_state is CrmState.POSSIBLE_MATCH  # similar name only
    assert views["100001"].crm_state is CrmState.NOT_IN_CRM

    org_id = setup.service.save_to_prospects(views["100001"].id)
    detail = setup.prospects.get_detail(org_id)
    assert detail is not None
    assert (detail.name, detail.website, detail.source) == (
        "Harbor Light Studio",
        "https://www.harborlight.example",
        RecordSource.DISCOVERY,
    )
    (game,) = detail.games
    assert game.title == "Lantern Tides" and game.store_url.endswith("/app/100001/")
    (contact,) = detail.contacts
    assert contact.email == "hello@harborlight.example"
    assert contact.provenance == "Support email listed on the store page"
    assert contact.source_url == "https://store.steampowered.com/app/100001/"
    after = setup.views()
    assert after["100001"].status is LeadStatus.SAVED
    assert after["100001"].crm_state is CrmState.GAME_IN_CRM

    # Adding a game to an existing prospect instead of creating a duplicate.
    setup.service.save_to_prospects(
        views["100006"].id, existing_organization_id=renamed, include_contact=False
    )
    renamed_detail = setup.prospects.get_detail(renamed)
    assert renamed_detail is not None
    assert [g.title for g in renamed_detail.games] == ["Starfall Ledger"]
    assert renamed_detail.contacts == ()
    assert setup.prospects.count() == 3
    assert [c.name for c in setup.service.duplicates_for(views["100005"].id)] == ["Quiet Owl"]


def test_website_contact_search(setup: Setup) -> None:
    setup.service.run(DiscoveryParams(max_candidates=20))
    views = setup.views()
    setup.site_pages = {
        "copperleaf.example/robots.txt": "User-agent: *\nAllow: /\n",
        "copperleaf.example/": '<a href="/contact">Contact</a>',
        "copperleaf.example/contact": "Business enquiries: bizdev@copperleaf.example",
    }
    result = setup.service.find_website_contacts(views["100002"].id)
    assert [(a.email, a.source_url) for a in result.addresses] == [
        ("bizdev@copperleaf.example", "http://copperleaf.example/contact")
    ]
    with pytest.raises(DiscoveryError, match="No official website"):
        setup.service.find_website_contacts(views["100003"].id)
    assert setup.prospects.search(ProspectQuery()).total == 0  # nothing saved automatically
