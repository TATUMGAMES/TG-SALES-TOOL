"""Transfer of desktop (SQLite) databases into PostgreSQL, with verification.

Realistic legacy databases are produced by building a sales history with the
real services, then writing it in the desktop SQLite format (schema created
by the desktop migration chain, timestamps as UTC text, JSON as text).
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from contextlib import closing
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from alembic import command
from sqlalchemy import JSON, Boolean, MetaData, select, text

from tg_sales.db.database import DEVICE_ID_KEY, Database
from tg_sales.db.models import Activity, Organization
from tg_sales.domain.enums import ActivityType, ProductLane, SettingScope
from tg_sales.domain.kpi import KpiFilters
from tg_sales.domain.opportunities import OpportunityDraft
from tg_sales.domain.periods import DateRange
from tg_sales.domain.prospects import ContactDraft, OrganizationDraft
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.domain.time import format_utc
from tg_sales.legacy.sqlite_database import (
    LegacyDatabaseError,
    alembic_config,
    create_sqlite_engine,
)
from tg_sales.legacy.transfer import NEW_ONLY_TABLES, transfer, write_report
from tg_sales.repositories.settings import SettingsRepository
from tg_sales.services.identity import CURRENT_ACTOR_KEY, ensure_local_actor
from tg_sales.services.kpis import KpiService
from tg_sales.services.pipeline import PipelineService
from tg_sales.services.prospects import ProspectService

from .conftest import FakeClock

pytestmark = pytest.mark.integration

STAGE = {s.key: s.id for s in DEFAULT_STAGES}
OCTOBER = DateRange(date(2026, 9, 1), date(2026, 10, 31))


def build_history(database: Database, clock: FakeClock) -> None:
    actor = ensure_local_actor(database)
    prospects = ProspectService(database, actor)
    pipeline = PipelineService(database, actor)
    for index in range(6):
        clock.set(datetime(2026, 9, 3 + index * 4, 15, tzinfo=UTC))
        org = prospects.create(
            OrganizationDraft(f"Example Studio {index}", website=f"https://studio{index}.example"),
            [ContactDraft(name=f"Contact {index}", email=f"c{index}@studio{index}.example")],
        )
        prospects.add_note(org, "Met at a conference — 販売 ñ")
        opp = pipeline.create_opportunity(
            OpportunityDraft(
                org, ProductLane.DATA_LICENSING, STAGE["contacted"], title=f"Deal {index}"
            )
        )
        clock.set(clock.current + timedelta(days=2))
        pipeline.log_activity(opp, ActivityType.EMAIL, note="Intro email")
        if index % 2 == 0:
            clock.set(clock.current + timedelta(days=3))
            pipeline.move(opp, STAGE["interested"])
        if index == 4:
            clock.set(clock.current + timedelta(days=1))
            pipeline.move(opp, STAGE["won"], reason_code="signed", reason_note="Signed")
        if index == 5:
            pipeline.add_task(opp, "Send sample data", clock.current + timedelta(days=5))
    clock.set(datetime(2026, 10, 30, tzinfo=UTC))


def _legacy_value(value: Any, column: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, datetime):
        return format_utc(value)
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(column.type, JSON):
        return json.dumps(value)
    if isinstance(column.type, Boolean):
        return int(bool(value))
    if hasattr(value, "value"):
        return value.value
    return value


def write_legacy_copy(database: Database, path: Path, revision: str = "head") -> Path:
    """Write ``database``'s rows into a desktop-format SQLite file at ``path``."""
    path.parent.mkdir(parents=True, exist_ok=True)
    engine = create_sqlite_engine(path)
    config = alembic_config()
    with engine.connect() as connection, connection.begin():
        config.attributes["connection"] = connection
        command.upgrade(config, revision)
    legacy = MetaData()
    legacy.reflect(engine)
    source = MetaData()
    source.reflect(database.engine)
    with closing(sqlite3.connect(path)) as raw, database.engine.connect() as pg:
        raw.execute("PRAGMA foreign_keys = OFF")
        raw.execute("DROP TRIGGER IF EXISTS trg_activities_no_update")
        raw.execute("DROP TRIGGER IF EXISTS trg_activities_no_delete")
        raw.execute("DELETE FROM pipeline_stages")
        for table in source.sorted_tables:
            if (
                table.name in NEW_ONLY_TABLES | {"alembic_version"}
                or table.name not in legacy.tables
            ):
                continue
            columns = [c for c in table.columns if c.name in legacy.tables[table.name].c]
            for row in pg.execute(select(table)).mappings():
                names = ", ".join(c.name for c in columns)
                marks = ", ".join("?" for _ in columns)
                raw.execute(
                    f"INSERT INTO {table.name} ({names}) VALUES ({marks})",  # noqa: S608
                    [_legacy_value(row[c.name], c) for c in columns],
                )
        raw.commit()
    engine.dispose()
    return path


def dashboard_numbers(database: Database) -> dict[str, Any]:
    report = KpiService(database, zone=UTC).dashboard(OCTOBER, KpiFilters()).report
    return {
        "metrics": {k: (m.value, len(m.rows)) for k, m in report.metrics.items()},
        "stages": [(s.stage_id, s.at_period_end, s.exits, s.median_days) for s in report.stages],
        "transitions": sorted((str(t.from_stage), t.to_stage, t.count) for t in report.transitions),
        "activity": sorted(
            (a.actor_id, str(a.lane), str(a.type), a.count) for a in report.activity_counts
        ),
    }


@pytest.fixture
def legacy(
    make_database: Callable[..., Database], clock: FakeClock, tmp_path: Path
) -> tuple[Path, Database]:
    original = make_database(clock)
    build_history(original, clock)
    return write_legacy_copy(original, tmp_path / "desktop" / "data" / "tg_sales.db"), original


def test_transfer_preserves_everything_and_kpis(
    legacy: tuple[Path, Database],
    make_database: Callable[..., Database],
    clock: FakeClock,
    tmp_path: Path,
) -> None:
    path, original = legacy
    before = path.read_bytes()
    target = make_database(clock)

    report = transfer(path, target, data_root=tmp_path / "new data")

    assert report.ok, report.to_markdown()
    assert path.read_bytes() == before  # original untouched
    assert report.tables["organizations"].inserted == 6
    assert report.tables["activities"].inserted == report.tables["activities"].source
    assert report.verification["stage_history_matches"]
    assert report.adopted_device_id == original.device_id
    reopened = Database.open(target.url, clock=clock)
    try:
        assert reopened.device_id == original.device_id
        with reopened.session() as session:
            actor = SettingsRepository(session).get(CURRENT_ACTOR_KEY, SettingScope.DEVICE)
        assert actor == ensure_local_actor(original)
        assert dashboard_numbers(reopened) == dashboard_numbers(original)
    finally:
        reopened.dispose()


def test_transfer_is_repeatable_without_duplicates(
    legacy: tuple[Path, Database], make_database: Callable[..., Database], clock: FakeClock
) -> None:
    path, _original = legacy
    target = make_database(clock)
    transfer(path, target, copy_files=False)
    with target.engine.connect() as connection:
        counts = {
            t: connection.scalar(text(f"SELECT count(*) FROM {t}"))  # noqa: S608
            for t in ("organizations", "contacts", "activities", "opportunities", "change_log")
        }
    again = transfer(path, target, copy_files=False)
    assert again.ok, again.to_markdown()
    assert all(r.inserted == 0 for r in again.tables.values())
    with target.engine.connect() as connection:
        for table, count in counts.items():
            assert connection.scalar(text(f"SELECT count(*) FROM {table}")) == count  # noqa: S608


def test_changed_rows_are_reported_not_overwritten(
    legacy: tuple[Path, Database], make_database: Callable[..., Database], clock: FakeClock
) -> None:
    path, _original = legacy
    target = make_database(clock)
    transfer(path, target, copy_files=False)
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(
            "UPDATE organizations SET name = 'Renamed On Desktop' WHERE name = 'Example Studio 1'"
        )
        raw.commit()
    again = transfer(path, target, copy_files=False)
    assert not again.ok
    assert again.tables["organizations"].conflicts == 1
    issue = next(i for i in again.issues if i.kind == "conflict")
    assert "name" in (issue.column or "")
    with target.session() as session:
        assert "Example Studio 1" in session.scalars(select(Organization.name)).all()


def test_malformed_and_orphan_rows_are_reported(
    legacy: tuple[Path, Database],
    make_database: Callable[..., Database],
    clock: FakeClock,
    tmp_path: Path,
) -> None:
    path, _original = legacy
    with closing(sqlite3.connect(path)) as raw:
        raw.execute("PRAGMA foreign_keys = OFF")
        org_id = raw.execute(
            "SELECT id FROM organizations WHERE name = 'Example Studio 2'"
        ).fetchone()[0]
        raw.execute("UPDATE organizations SET created_at_utc = 'yesterday' WHERE id = ?", (org_id,))
        raw.execute("DROP TRIGGER IF EXISTS trg_activities_no_update")
        raw.execute(
            "UPDATE activities SET payload = '{not json' WHERE id = "
            "(SELECT id FROM activities WHERE type = 'email' LIMIT 1)"
        )
        raw.commit()
    target = make_database(clock)
    report = transfer(path, target, copy_files=False)

    kinds = {(i.table, i.kind, i.column) for i in report.issues}
    assert ("organizations", "invalid", "created_at_utc") in kinds
    assert ("activities", "invalid", "payload") in kinds
    # Rows that depended on the unreadable studio are reported, not silently dropped.
    assert any(
        i.table == "contacts" and "missing organizations" in i.message for i in report.issues
    )
    saved = next(i for i in report.issues if i.column == "created_at_utc")
    assert saved.original["created_at_utc"] == "yesterday"
    json_path, md_path = write_report(report, tmp_path / "reports")
    assert json.loads(json_path.read_text(encoding="utf-8"))["ok"] is False
    assert "NEEDS ATTENTION" in md_path.read_text(encoding="utf-8")
    with target.session() as session:
        names = session.scalars(select(Organization.name)).all()
    assert "Example Studio 2" not in names and len(names) == 5


def test_dry_run_changes_nothing(
    legacy: tuple[Path, Database], make_database: Callable[..., Database], clock: FakeClock
) -> None:
    path, _original = legacy
    target = make_database(clock)
    report = transfer(path, target, dry_run=True)
    assert report.tables["organizations"].inserted == 6
    with target.session() as session:
        assert session.scalars(select(Organization)).all() == []
        assert session.scalars(select(Activity)).all() == []


def test_older_desktop_schema_is_upgraded_on_a_copy(
    make_database: Callable[..., Database], clock: FakeClock, tmp_path: Path
) -> None:
    path = tmp_path / "old.db"
    engine = create_sqlite_engine(path)
    config = alembic_config()
    with engine.connect() as connection, connection.begin():
        config.attributes["connection"] = connection
        command.upgrade(config, "0001")
    engine.dispose()
    with closing(sqlite3.connect(path)) as raw:
        raw.execute(
            "INSERT INTO organizations (id, name, normalized_name, company_type, source, tags, "
            "created_at_utc, updated_at_utc, created_by_device_id) "
            "VALUES (?, ?, ?, 'unknown', 'manual', '[]', ?, ?, ?)",
            (
                "0190a0b0-0000-7000-8000-000000000001",
                "First Release Studio",
                "first release studio",
                "2026-02-01T10:00:00.000000Z",
                "2026-02-01T10:00:00.000000Z",
                "0190a0b0-0000-7000-8000-0000000000aa",
            ),
        )
        raw.commit()
    before = path.read_bytes()
    target = make_database(clock)
    report = transfer(path, target, copy_files=False)
    assert report.source_revision == "0001"
    assert report.ok, report.to_markdown()
    assert path.read_bytes() == before
    with target.session() as session:
        assert session.scalars(select(Organization.name)).all() == ["First Release Studio"]


def test_non_database_file_is_refused(
    make_database: Callable[..., Database], tmp_path: Path
) -> None:
    junk = tmp_path / "junk.db"
    junk.write_bytes(b"this is not sqlite" * 100)
    with pytest.raises(LegacyDatabaseError):
        transfer(junk, make_database())


def test_existing_installation_keeps_its_device_identity(
    legacy: tuple[Path, Database], make_database: Callable[..., Database], clock: FakeClock
) -> None:
    path, original = legacy
    target = make_database(clock)
    ProspectService(target, ensure_local_actor(target)).create(OrganizationDraft("Already Here"))
    report = transfer(path, target, copy_files=False)
    assert report.adopted_device_id is None
    assert report.tables["settings"].skipped_device_settings >= 1
    with target.session() as session:
        device = SettingsRepository(session).get(DEVICE_ID_KEY, SettingScope.DEVICE)
    assert device == target.device_id != original.device_id
    assert report.ok, report.to_markdown()
