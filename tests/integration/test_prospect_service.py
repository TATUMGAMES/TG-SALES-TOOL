from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from sqlalchemy import select

from tg_sales.db.database import Database
from tg_sales.db.models import Activity, Opportunity
from tg_sales.domain.enums import (
    ActivityType,
    ContactStatus,
    GameRole,
    OrganizationType,
    ProductLane,
    ReleasePrecision,
)
from tg_sales.domain.prospects import (
    ContactDraft,
    GameDraft,
    MatchStrength,
    OrganizationDraft,
    ProspectQuery,
)
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.ledger import ActivityLedger
from tg_sales.services.opportunities import OpportunityService
from tg_sales.services.prospects import (
    ProspectNotFoundError,
    ProspectService,
    ProspectValidationError,
)

pytestmark = pytest.mark.integration


@pytest.fixture
def actor(database: Database) -> str:
    return ensure_local_actor(database)


@pytest.fixture
def service(database: Database, actor: str) -> ProspectService:
    return ProspectService(database, actor)


def names(service: ProspectService, **query: object) -> list[str]:
    return [r.name for r in service.search(ProspectQuery(**query)).rows]  # type: ignore[arg-type]


def test_create_with_contact_and_timeline(service: ProspectService, database: Database) -> None:
    org_id = service.create(
        OrganizationDraft(
            "  Pixel Forge Studios ",
            "WWW.PixelForge.Example/",
            OrganizationType.STUDIO,
            "Lisbon",
            "Portugal",
            ("indie", "Indie", "vr"),
            "Met at a conference",
        ),
        [
            ContactDraft(
                name="Ana Ruiz",
                email="Ana@PixelForge.Example",
                social_urls={"linkedin": "linkedin.com/in/ana-example"},
                status=ContactStatus.ATTEMPTED,
                provenance="Studio website",
            )
        ],
    )
    detail = service.get_detail(org_id)
    assert detail is not None
    assert detail.name == "Pixel Forge Studios"
    assert detail.website == "https://www.pixelforge.example"
    assert detail.domain == "pixelforge.example"
    assert detail.tags == ("indie", "vr")
    (contact,) = detail.contacts
    assert contact.email == "ana@pixelforge.example"
    assert contact.social_urls == {"linkedin": "https://linkedin.com/in/ana-example"}
    assert contact.status is ContactStatus.ATTEMPTED
    assert [e.summary for e in detail.timeline] == ["Prospect created"]
    assert [link.label for link in detail.links] == ["Website", "Ana Ruiz · Linkedin"]
    summary = service.search(ProspectQuery()).rows[0]
    assert summary.contact_count == 1
    assert summary.company_type is OrganizationType.STUDIO


@pytest.mark.parametrize(
    ("draft", "contact", "message"),
    [
        (OrganizationDraft("   "), None, "needs a name"),
        (OrganizationDraft("!!!"), None, "needs a name"),
        (OrganizationDraft("A", "javascript:alert(1)"), None, "not a valid website"),
        (OrganizationDraft("A"), ContactDraft(email="nope"), "not a valid email"),
        (OrganizationDraft("A"), ContactDraft(role_title="CEO"), "needs a name, an email"),
        (
            OrganizationDraft("A"),
            ContactDraft(name="x", social_urls={"x": "ftp://a"}),
            "web address",
        ),
    ],
)
def test_validation(
    service: ProspectService,
    draft: OrganizationDraft,
    contact: ContactDraft | None,
    message: str,
) -> None:
    with pytest.raises(ProspectValidationError, match=message) as info:
        service.create(draft, [contact] if contact else [])
    assert info.value.suggested_action
    assert service.count() == 0


def test_duplicate_detection_allows_similar_names(service: ProspectService) -> None:
    first = service.create(
        OrganizationDraft("Moon Owl Games", "moonowl.example"),
        [ContactDraft(email="chloe@moonowl.example")],
    )
    by_domain = service.find_duplicates(OrganizationDraft("Other Name", "https://moonowl.example"))
    assert [(c.id, c.strength) for c in by_domain] == [(first, MatchStrength.STRONG)]
    by_email = service.find_duplicates(OrganizationDraft("Other"), ["CHLOE@moonowl.example"])
    assert by_email[0].strength is MatchStrength.STRONG
    similar = service.find_duplicates(OrganizationDraft("Moon Owl Game", "moon-owl.example"))
    assert [c.strength for c in similar] == [MatchStrength.SIMILAR]
    assert service.find_duplicates(OrganizationDraft("Moon Owl Games"), exclude_id=first) == []
    service.create(OrganizationDraft("Moon Owl Game", "moon-owl.example"))  # still allowed
    assert service.count() == 2


def test_update_records_field_changes(service: ProspectService, database: Database) -> None:
    org_id = service.create(OrganizationDraft("Northwind", "northwind.example"))
    assert not service.update(org_id, OrganizationDraft("Northwind", "northwind.example"))
    assert service.update(
        org_id, OrganizationDraft("Northwind Interactive", "northwind.example", country="NO")
    )
    with database.session() as session:
        change = session.scalars(
            select(Activity).where(Activity.type == ActivityType.FIELD_CHANGE)
        ).one()
        assert change.payload["entity"] == "organizations"
        assert change.payload["changes"] == {
            "name": {"old": "Northwind", "new": "Northwind Interactive"},
            "country": {"old": None, "new": "NO"},
        }
    detail = service.get_detail(org_id)
    assert detail is not None
    assert detail.timeline[0].summary == "Prospect updated: country, name"
    with pytest.raises(ProspectNotFoundError):
        service.update("missing", OrganizationDraft("X"))


def test_archive_restore_and_search_filters(service: ProspectService) -> None:
    a = service.create(OrganizationDraft("Alpha Games", "alpha.example", OrganizationType.STUDIO))
    b = service.create(OrganizationDraft("Beta Publishing", None, OrganizationType.PUBLISHER))
    assert service.set_archived([a], True) == 1
    assert service.set_archived([a], True) == 0
    assert names(service) == ["Beta Publishing"]
    assert names(service, include_archived=True) == ["Alpha Games", "Beta Publishing"]
    assert names(service, company_type=OrganizationType.PUBLISHER) == ["Beta Publishing"]
    assert service.count() == 2
    assert service.count(include_archived=False) == 1
    detail = service.get_detail(a)
    assert detail is not None and detail.archived
    assert detail.timeline[0].summary == "Prospect archived"
    assert service.set_archived([a, b], False) == 1
    assert names(service) == ["Alpha Games", "Beta Publishing"]


def test_tags_bulk_and_filter(service: ProspectService) -> None:
    a = service.create(OrganizationDraft("Alpha", tags=("VR",)))
    b = service.create(OrganizationDraft("Beta"))
    assert service.add_tag([a, b], " vr ") == 1  # Alpha already has it (case-insensitive)
    assert names(service, tag="Vr") == ["Alpha", "Beta"]
    assert [t.casefold() for t in service.all_tags()] == ["vr"]  # one entry per tag
    assert service.remove_tag([a, b], "VR") == 2
    assert names(service, tag="vr") == []
    with pytest.raises(ProspectValidationError):
        service.add_tag([a], "  ")


def test_search_covers_contacts_games_and_escapes_wildcards(service: ProspectService) -> None:
    a = service.create(
        OrganizationDraft("Pixel Forge", "pixelforge.example", location="Kraków"),
        [ContactDraft(name="Ana Ruiz", email="ana@pixelforge.example", role_title="Producer")],
    )
    service.add_game(a, GameDraft("Sky Rails"))
    service.create(OrganizationDraft("100% Indie"))
    service.create(OrganizationDraft("Under_Score Games"))
    assert names(service, text="ana@pixel") == ["Pixel Forge"]
    assert names(service, text="RUIZ") == ["Pixel Forge"]
    assert names(service, text="producer") == ["Pixel Forge"]
    assert names(service, text="sky rails") == ["Pixel Forge"]
    assert names(service, text="pixelforge.example") == ["Pixel Forge"]
    assert names(service, text="pixel-forge") == ["Pixel Forge"]  # punctuation-insensitive name
    assert names(service, text="100%") == ["100% Indie"]
    assert names(service, text="%") == ["100% Indie"]
    assert names(service, text="_") == ["Under_Score Games"]
    assert names(service, text="nothing matches this") == []


def test_search_limit_reports_total(service: ProspectService) -> None:
    for i in range(5):
        service.create(OrganizationDraft(f"Studio {i}"))
    result = service.search(ProspectQuery(limit=3))
    assert len(result.rows) == 3
    assert result.total == 5
    assert result.truncated


def test_notes_contacts_and_games(service: ProspectService) -> None:
    org_id = service.create(OrganizationDraft("Glass Fern"))
    service.add_note(org_id, "  Prefers email  ")
    with pytest.raises(ProspectValidationError):
        service.add_note(org_id, "   ")
    contact_id = service.add_contact(
        org_id, ContactDraft(name="Ivy", email="ivy@glassfern.example")
    )
    assert service.contact_email_in_use("IVY@glassfern.example") == ["Glass Fern"]
    assert (
        service.contact_email_in_use("ivy@glassfern.example", exclude_contact_id=contact_id) == []
    )
    assert service.update_contact(
        contact_id,
        ContactDraft(
            name="Ivy Chen", email="ivy@glassfern.example", status=ContactStatus.RESPONDED
        ),
    )
    assert service.set_contact_archived(contact_id, True)
    assert not service.set_contact_archived(contact_id, True)
    first_game = service.add_game(
        org_id,
        GameDraft(
            "Fern Tales",
            GameRole.PUBLISHER,
            "PC",
            "store.example/app/1",
            date(2027, 7, 1),
            ReleasePrecision.QUARTER,
        ),
    )
    other = service.create(OrganizationDraft("Fern Dev"))
    assert (
        service.add_game(other, GameDraft("Fern Tales", store_url="https://store.example/app/1"))
        == first_game
    )
    detail = service.get_detail(org_id)
    assert detail is not None
    (contact,) = detail.contacts
    assert (contact.name, contact.status, contact.archived) == (
        "Ivy Chen",
        ContactStatus.RESPONDED,
        True,
    )
    (game,) = detail.games
    assert (game.role, game.release_precision) == (GameRole.PUBLISHER, ReleasePrecision.QUARTER)
    summaries = [e.summary for e in detail.timeline]
    assert "Note: Prefers email" in summaries
    assert "Contact archived" in summaries
    assert any(s.startswith("Contact updated") for s in summaries)
    assert (
        service.search(ProspectQuery(text="glass")).rows[0].contact_count == 0
    )  # archived contact
    with pytest.raises(ProspectValidationError):
        service.add_game(org_id, GameDraft("  "))


def test_follow_ups_and_opportunities_in_detail(
    service: ProspectService, database: Database, actor: str
) -> None:
    org_id = service.create(OrganizationDraft("Deal Co"))
    with database.session() as session:
        ledger = ActivityLedger(session, actor, database.clock)
        opportunities = OpportunityService(session, ledger, database.clock)
        open_opp = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.DATA_LICENSING,
            stage_id=DEFAULT_STAGES[2].id,
            title="Historical data",
        )
        won = opportunities.create(
            organization_id=org_id,
            product_lane=ProductLane.MIKROS_MARKETING,
            stage_id=DEFAULT_STAGES[0].id,
        )
        opportunities.move_to_stage(won.id, DEFAULT_STAGES[7].id)
        session.flush()
        stored = session.get(Opportunity, open_opp.id)
        assert stored is not None
        stored.next_action_at_utc = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
        stored.next_action_note = "Send sample data"
        won_row = session.get(Opportunity, won.id)
        assert won_row is not None
        won_row.next_action_at_utc = datetime(2026, 10, 30, tzinfo=UTC)
    detail = service.get_detail(org_id)
    assert detail is not None
    assert len(detail.opportunities) == 2
    assert [o.title for o in detail.follow_ups] == ["Historical data"]  # closed ones excluded
    summary = service.search(ProspectQuery()).rows[0]
    assert summary.open_opportunity_count == 1
    assert summary.next_follow_up == datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
    assert any(e.summary == "Moved to Won" for e in detail.timeline)


def test_export_csv_is_spreadsheet_safe(service: ProspectService, tmp_path: Path) -> None:
    a = service.create(
        OrganizationDraft("=cmd|' /C calc'!A0", notes="+SUM(1)", tags=("a", "b")),
        [ContactDraft(name="@Ana", email="ana@x.example")],
    )
    b = service.create(OrganizationDraft("Éclair Jeux", "eclair.example"))
    target = tmp_path / "exports" / "prospects.csv"
    assert service.export_csv(target, [b, a, "missing"]) == 2
    assert target.read_bytes().startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][0] == "Name"
    assert rows[1][0] == "Éclair Jeux"
    assert rows[2][0] == "'=cmd|' /C calc'!A0"
    assert rows[2][9] == "'+SUM(1)"
    assert rows[2][5] == "a; b"
    assert rows[2][6].startswith("'@Ana")
    assert not list(target.parent.glob("*.partial"))
    assert service.ids_for_query(ProspectQuery()) == [a, b]  # ordered by normalized name
