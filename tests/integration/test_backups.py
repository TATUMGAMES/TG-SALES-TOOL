"""Backups: create, verify, list, export, retention and restore-with-swap."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.engine import URL
from tests.integration.conftest import FakeClock
from tests.pg import PgTestServer

from tg_sales.db.database import Database
from tg_sales.db.models import Organization
from tg_sales.services.backups import BackupError, BackupManager, PgTools

pytestmark = pytest.mark.integration


@pytest.fixture
def tools(pg_server: PgTestServer) -> PgTools:
    bin_dir = pg_server.runtime.bin_dir if pg_server.runtime else None
    found = PgTools.find(bin_dir)
    if found is None:
        pytest.skip("pg_dump/pg_restore not available")
    return found


@pytest.fixture
def live(pg_url: URL, clock: FakeClock) -> Iterator[Database]:
    database = Database.open(pg_url, clock=clock)
    yield database
    database.dispose()


@pytest.fixture
def manager(
    tools: PgTools, live: Database, pg_server: PgTestServer, tmp_path: Path, clock: FakeClock
) -> BackupManager:
    return BackupManager(
        tools,
        live.url,
        tmp_path / "backups ü",
        clock,
        admin_url=pg_server.url_for("postgres"),
    )


def _add(database: Database, name: str) -> None:
    with database.session() as session:
        session.add(Organization(name=name, normalized_name=name.lower()))


def _names(url: URL) -> list[str]:
    database = Database.open(url)
    try:
        with database.session() as session:
            return sorted(session.scalars(select(Organization.name)))
    finally:
        database.dispose()


def test_create_verifies_and_describes_backup(manager: BackupManager, live: Database) -> None:
    _add(live, "Example Studio")
    info = manager.create()
    assert info.verified
    assert info.reason == "manual"
    assert info.table_counts["organizations"] == 1
    assert info.schema_revision == "0001"
    assert (manager.folder / info.name).is_file()
    assert not list(manager.folder.glob("*.partial"))
    assert [entry.name for entry in manager.list()] == [info.name]
    assert manager.verify(info.name).verified


def test_damaged_backup_is_detected(manager: BackupManager) -> None:
    info = manager.create()
    path = manager.folder / info.name
    path.write_bytes(path.read_bytes()[:-50] + b"x" * 50)
    with pytest.raises(BackupError, match="damaged"):
        manager.verify(info.name)


def test_path_outside_folder_is_refused(manager: BackupManager) -> None:
    for name in ("../tg_sales_backup_20260101T000000000Z_manual.dump", "secrets.txt", ""):
        with pytest.raises(BackupError):
            manager.path(name)


def test_export_refuses_to_overwrite(manager: BackupManager, tmp_path: Path) -> None:
    info = manager.create()
    target = tmp_path / "usb drive"
    exported = manager.export(info.name, target)
    assert exported.read_bytes() == (manager.folder / info.name).read_bytes()
    with pytest.raises(FileExistsError):
        manager.export(info.name, target)
    manager.export(info.name, target, overwrite=True)


def test_retention_keeps_latest_and_monthly(manager: BackupManager, clock: FakeClock) -> None:
    manager.keep_latest, manager.keep_monthly = 3, 2
    start = datetime(2026, 5, 15, tzinfo=UTC)
    for offset in range(0, 150, 10):  # mid-May to early October
        clock.set(start + timedelta(days=offset))
        manager.create("scheduled")
    kept = manager.list()
    months = {entry.created_at.strftime("%Y-%m") for entry in kept}
    assert len(kept) <= 3 + 2
    assert kept[0].created_at.date() == (start + timedelta(days=140)).date()
    assert {"2026-10", "2026-09"} <= months


def test_restore_swaps_in_backup_and_keeps_previous(
    manager: BackupManager, live: Database, pg_server: PgTestServer
) -> None:
    _add(live, "Before Backup")
    info = manager.create()
    _add(live, "After Backup")

    outcome = manager.restore(info.name, before_swap=live.dispose)

    assert _names(live.url) == ["Before Backup"]
    assert _names(pg_server.url_for(outcome.previous_database)) == ["After Backup", "Before Backup"]
    assert outcome.safety_backup.table_counts["organizations"] == 2
    pg_server.drop_database(pg_server.url_for(outcome.previous_database))


def test_restored_database_keeps_safeguards(manager: BackupManager, live: Database) -> None:
    info = manager.create()
    manager.restore(info.name, before_swap=live.dispose)
    reopened = Database.open(live.url)
    try:
        assert reopened.check_integrity(full=True).ok
        with reopened.engine.connect() as connection:
            names = set(connection.scalars(text("SELECT tgname FROM pg_trigger")))
        assert "trg_activities_immutable" in names
    finally:
        reopened.dispose()


def test_restore_of_damaged_backup_leaves_data_unchanged(
    manager: BackupManager, live: Database
) -> None:
    _add(live, "Keep Me")
    info = manager.create()
    path = manager.folder / info.name
    path.write_bytes(b"garbage")
    with pytest.raises(BackupError):
        manager.restore(info.name, before_swap=live.dispose)
    assert _names(live.url) == ["Keep Me"]


def test_restore_requires_administrator(
    tools: PgTools, live: Database, tmp_path: Path, clock: FakeClock
) -> None:
    manager = BackupManager(tools, live.url, tmp_path / "b", clock)
    info = manager.create()
    assert not manager.can_restore
    with pytest.raises(BackupError, match="administrator"):
        manager.restore(info.name, before_swap=lambda: None)


def test_unwritable_folder_gives_actionable_error(
    tools: PgTools, live: Database, tmp_path: Path, clock: FakeClock
) -> None:
    blocker = tmp_path / "file"
    blocker.write_text("x")
    manager = BackupManager(tools, live.url, blocker / "backups", clock)
    with pytest.raises(BackupError) as info:
        manager.create()
    assert "writable" in info.value.suggested_action
