from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError, StatementError

from tg_sales.db.database import Database
from tg_sales.db.engine import ImmutableRecordError
from tg_sales.db.models import (
    Activity,
    Contact,
    Game,
    GameOrganization,
    Opportunity,
    Organization,
    PipelineStage,
)
from tg_sales.domain.enums import (
    ActivityType,
    ContactStatus,
    GameRole,
    ProductLane,
    ReleasePrecision,
)
from tg_sales.domain.ids import is_valid_id, uuid7_timestamp_ms
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.repositories.settings import SettingsRepository
from tg_sales.services.identity import DEFAULT_ACTOR_NAME, ensure_local_actor

pytestmark = pytest.mark.integration

FIRST_STAGE = DEFAULT_STAGES[0].id


def add_org(database: Database, name: str = "Example Studio") -> str:
    with database.session() as session:
        org = Organization(name=name, normalized_name=name.lower())
        session.add(org)
        session.flush()
        return org.id


def test_new_rows_get_ids_timestamps_and_device(database: Database) -> None:
    with database.session() as session:
        org = Organization(name="Example Studio", normalized_name="example studio")
        session.add(org)
        session.flush()
        assert is_valid_id(org.id)
        assert uuid7_timestamp_ms(org.id) > 0
        assert org.created_at_utc.tzinfo is not None
        assert org.updated_at_utc == org.created_at_utc
        assert org.created_by_device_id == database.device_id
        assert org.deleted_at_utc is None
        assert org.tags == []


def test_updates_refresh_updated_at_only(database: Database) -> None:
    org_id = add_org(database)
    with database.session() as session:
        org = session.get(Organization, org_id)
        assert org is not None
        created, updated = org.created_at_utc, org.updated_at_utc
        org.website = "https://example.com"
    with database.session() as session:
        org = session.get(Organization, org_id)
        assert org is not None
        assert org.created_at_utc == created
        assert org.updated_at_utc > updated


def test_timestamps_stored_as_timestamptz_in_utc(database: Database) -> None:
    add_org(database)
    with database.engine.connect() as connection:
        column_type = connection.scalar(
            text(
                "SELECT data_type FROM information_schema.columns "
                "WHERE table_name = 'organizations' AND column_name = 'created_at_utc'"
            )
        )
        stored = connection.scalar(text("SELECT created_at_utc FROM organizations"))
    assert column_type == "timestamp with time zone"
    assert isinstance(stored, datetime)
    assert stored.utcoffset() == timedelta(0)


def test_naive_datetime_is_rejected(database: Database) -> None:
    org_id = add_org(database)
    with pytest.raises(StatementError, match="Naive datetime"), database.session() as session:
        org = session.get(Organization, org_id)
        assert org is not None
        org.deleted_at_utc = datetime(2026, 1, 1)  # noqa: DTZ001 - deliberately naive


def test_soft_delete_keeps_row_as_tombstone(database: Database) -> None:
    org_id = add_org(database)
    with database.session() as session:
        org = session.get(Organization, org_id)
        assert org is not None
        org.deleted_at_utc = database.clock.now()
    with database.session() as session:
        org = session.get(Organization, org_id)
        assert org is not None
        assert org.is_deleted
        assert org.updated_at_utc >= org.deleted_at_utc  # type: ignore[operator]


def test_organization_has_many_contacts_games_and_opportunities(database: Database) -> None:
    org_id = add_org(database)
    with database.session() as session:
        session.add_all(
            [
                Contact(organization_id=org_id, name="Ana", business_email="ana@studio.example"),
                Contact(organization_id=org_id, name="Ben"),
            ]
        )
        game_a = Game(title="Game A", store="steam", store_id="100")
        game_b = Game(title="Game B", store="steam", store_id="200")
        session.add_all([game_a, game_b])
        session.flush()
        session.add_all(
            [
                GameOrganization(
                    game_id=game_a.id, organization_id=org_id, role=GameRole.DEVELOPER
                ),
                GameOrganization(
                    game_id=game_a.id, organization_id=org_id, role=GameRole.PUBLISHER
                ),
                GameOrganization(
                    game_id=game_b.id, organization_id=org_id, role=GameRole.DEVELOPER
                ),
            ]
        )
        for lane in (ProductLane.DATA_LICENSING, ProductLane.MIKROS_MARKETING):
            session.add(
                Opportunity(organization_id=org_id, product_lane=lane, stage_id=FIRST_STAGE)
            )
    with database.session() as session:
        assert len(session.scalars(select(Contact)).all()) == 2
        assert len(session.scalars(select(GameOrganization)).all()) == 3
        lanes = set(session.scalars(select(Opportunity.product_lane)))
        assert lanes == {ProductLane.DATA_LICENSING, ProductLane.MIKROS_MARKETING}


def test_contact_status_defaults_to_unknown(database: Database) -> None:
    org_id = add_org(database)
    with database.session() as session:
        contact = Contact(organization_id=org_id, business_email="x@studio.example")
        session.add(contact)
        session.flush()
        assert contact.contact_status is ContactStatus.UNKNOWN


def test_game_release_date_and_precision(database: Database) -> None:
    with database.session() as session:
        session.add(
            Game(
                title="Upcoming",
                release_date=date(2026, 12, 1),
                release_precision=ReleasePrecision.MONTH,
            )
        )
        session.add(Game(title="Coming soon"))
    with database.session() as session:
        games = {g.title: g for g in session.scalars(select(Game))}
        assert games["Upcoming"].release_date == date(2026, 12, 1)
        assert games["Coming soon"].release_date is None
        assert games["Coming soon"].release_precision is ReleasePrecision.UNKNOWN


def test_foreign_keys_are_enforced(database: Database) -> None:
    with pytest.raises(IntegrityError), database.session() as session:
        session.add(Contact(organization_id="00000000-0000-7000-8000-000000000000"))


def test_store_ids_unique_among_live_rows_only(database: Database) -> None:
    with database.session() as session:
        game = Game(title="Original", store="steam", store_id="42")
        session.add(game)
        session.flush()
        game_id = game.id
    with pytest.raises(IntegrityError), database.session() as session:
        session.add(Game(title="Duplicate", store="steam", store_id="42"))
    with database.session() as session:
        tombstoned = session.get(Game, game_id)
        assert tombstoned is not None
        tombstoned.deleted_at_utc = database.clock.now()
    with database.session() as session:
        session.add(Game(title="Re-added", store="steam", store_id="42"))
        session.add(Game(title="No store id A"))
        session.add(Game(title="No store id B"))


def test_probability_and_value_constraints(database: Database) -> None:
    org_id = add_org(database)
    for field, value in (("probability", 1.5), ("estimated_value", -1.0)):
        with pytest.raises(IntegrityError), database.session() as session:
            session.add(
                Opportunity(
                    organization_id=org_id,
                    product_lane=ProductLane.PUBLISHER_PARTNERSHIP,
                    stage_id=FIRST_STAGE,
                    **{field: value},
                )
            )


def test_invalid_enum_value_is_rejected(database: Database) -> None:
    org_id = add_org(database)
    with pytest.raises(StatementError), database.session() as session:
        session.add(
            Opportunity(
                organization_id=org_id,
                product_lane="crypto",  # type: ignore[arg-type]
                stage_id=FIRST_STAGE,
            )
        )


def _add_activity(database: Database) -> str:
    with database.session() as session:
        activity = Activity(
            type=ActivityType.NOTE, occurred_at_utc=database.clock.now(), payload={"text": "hi"}
        )
        session.add(activity)
        session.flush()
        return activity.id


def test_activities_cannot_be_changed_through_the_orm(database: Database) -> None:
    event_id = _add_activity(database)
    with pytest.raises(ImmutableRecordError), database.session() as session:
        activity = session.get(Activity, event_id)
        assert activity is not None
        activity.type = ActivityType.EMAIL
    with pytest.raises(ImmutableRecordError), database.session() as session:
        activity = session.get(Activity, event_id)
        session.delete(activity)


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE activities SET type = 'email' WHERE id = :id",
        "DELETE FROM activities WHERE id = :id",
        "TRUNCATE activities CASCADE",
    ],
)
def test_activities_cannot_be_changed_with_raw_sql(database: Database, statement: str) -> None:
    event_id = _add_activity(database)
    with (
        pytest.raises(IntegrityError, match="immutable"),
        database.engine.connect() as connection,
        connection.begin(),
    ):
        connection.execute(text(statement), {"id": event_id})


def test_settings_repository_scopes(database: Database) -> None:
    with database.session() as session:
        settings = SettingsRepository(session)
        settings.set("theme_hint", "dark")
        settings.set("theme_hint", "light")
        assert settings.get("theme_hint") == "light"
        assert settings.get("missing", default=7) == 7


def test_local_actor_created_once(database: Database) -> None:
    first = ensure_local_actor(database)
    assert ensure_local_actor(database) == first
    with database.session() as session:
        from tg_sales.db.models import Actor

        actors = session.scalars(select(Actor)).all()
        assert [(a.id, a.display_name) for a in actors] == [(first, DEFAULT_ACTOR_NAME)]


def test_stages_query_excludes_archived(database: Database) -> None:
    from tg_sales.repositories.stages import StageRepository

    with database.session() as session:
        stage = session.get(PipelineStage, DEFAULT_STAGES[1].id)
        assert stage is not None
        stage.archived_at_utc = database.clock.now()
    with database.session() as session:
        repo = StageRepository(session)
        assert len(repo.list()) == len(DEFAULT_STAGES) - 1
        assert len(repo.list(include_archived=True)) == len(DEFAULT_STAGES)
