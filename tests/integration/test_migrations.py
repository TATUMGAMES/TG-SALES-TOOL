"""PostgreSQL schema migrations: creation, upgrade safety, refusal of unknown databases."""

from __future__ import annotations

import shutil
from collections.abc import Callable
from pathlib import Path

import pytest
from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.engine import URL
from tests.pg import PgTestServer

from tg_sales.db.database import (
    MIGRATIONS_DIR,
    Database,
    DatabaseCorruptError,
    DatabaseOpenError,
    DatabaseVersionError,
    MigrationError,
    alembic_config,
    head_revision,
)
from tg_sales.db.engine import create_pg_engine
from tg_sales.db.models import ENTITY_MODELS, SYNCED_TABLES, Base, Organization, PipelineStage
from tg_sales.domain.stages import DEFAULT_STAGES

pytestmark = pytest.mark.integration

HEAD = "0001"

EXTRA_REVISION = f'''"""Test-only revision adding a column."""

import sqlalchemy as sa
from alembic import op

revision = "0099"
down_revision = {HEAD!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("test_column", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("organizations", "test_column")
'''

FAILING_REVISION = f'''"""Test-only revision that fails after changing the schema."""

import sqlalchemy as sa
from alembic import op

revision = "0099"
down_revision = {HEAD!r}
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("organizations", sa.Column("half_done", sa.Text(), nullable=True))
    op.execute("UPDATE organizations SET name = 'CHANGED'")
    raise RuntimeError("simulated migration failure")


def downgrade() -> None:
    pass
'''  # noqa: S608


def _extra_chain(tmp_path: Path, name: str, body: str) -> Path:
    migrations = tmp_path / "migrations"
    shutil.copytree(MIGRATIONS_DIR, migrations, ignore=shutil.ignore_patterns("__pycache__"))
    (migrations / "versions" / name).write_text(body, encoding="utf-8")
    return migrations


def test_new_database_is_created_at_latest_revision(database: Database) -> None:
    assert database.schema_revision() == HEAD == head_revision()
    tables = set(inspect(database.engine).get_table_names())
    assert {model.__tablename__ for model in ENTITY_MODELS} | {"change_log"} <= tables


def test_every_table_has_bookkeeping_columns(database: Database) -> None:
    inspector = inspect(database.engine)
    for model in ENTITY_MODELS:
        columns = {c["name"] for c in inspector.get_columns(model.__tablename__)}
        assert {
            "id",
            "created_at_utc",
            "updated_at_utc",
            "created_by_device_id",
            "deleted_at_utc",
        } <= columns, model.__tablename__


def test_migrations_match_models(database: Database) -> None:
    with database.engine.connect() as connection:
        context = MigrationContext.configure(connection, opts={"compare_type": True})
        assert compare_metadata(context, Base.metadata) == []


def test_default_stages_seeded_with_shared_ids(database: Database) -> None:
    with database.session() as session:
        stages = session.scalars(select(PipelineStage).order_by(PipelineStage.sort_order)).all()
        assert [(s.id, s.name, s.sort_order, s.outcome) for s in stages] == [
            (d.id, d.name, d.sort_order, d.outcome) for d in DEFAULT_STAGES
        ]
        assert {s.created_by_device_id for s in stages} == {"00000000-0000-0000-0000-000000000000"}


def test_seeded_stages_have_no_change_history(database: Database) -> None:
    # Identical on every computer, so they must not look like local edits.
    with database.engine.connect() as connection:
        assert connection.scalar(text("SELECT count(*) FROM change_log")) == 0


def test_safeguard_triggers_exist(database: Database) -> None:
    with database.engine.connect() as connection:
        names = set(
            connection.scalars(text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal"))
        )
    assert {"trg_activities_immutable", "trg_activities_no_truncate"} <= names
    assert {f"trg_{table}_change_log" for table in SYNCED_TABLES} <= names


def test_foreign_keys_are_deferrable(database: Database) -> None:
    with database.engine.connect() as connection:
        rows = connection.execute(
            text("SELECT conname, condeferrable FROM pg_constraint WHERE contype = 'f'")
        ).all()
    assert rows
    assert all(deferrable for _name, deferrable in rows)


def test_downgrade_and_upgrade_round_trip(database: Database) -> None:
    config = alembic_config()
    with database.engine.connect() as connection, connection.begin():
        config.attributes["connection"] = connection
        command.downgrade(config, "base")
    assert set(inspect(database.engine).get_table_names()) <= {"alembic_version"}
    with database.engine.connect() as connection, connection.begin():
        config.attributes["connection"] = connection
        command.upgrade(config, "head")
    assert database.schema_revision() == HEAD


def test_reopen_keeps_device_id_and_skips_migration(pg_url: URL) -> None:
    calls: list[tuple[str, str]] = []

    def backup(old: str, new: str) -> Path:
        calls.append((old, new))
        return Path("unused")

    first = Database.open(pg_url, pre_upgrade_backup=backup)
    device = first.device_id
    first.dispose()
    second = Database.open(pg_url, pre_upgrade_backup=backup)
    try:
        assert second.device_id == device
        assert second.pre_migration_backup is None
        assert calls == []
    finally:
        second.dispose()


def test_upgrade_backs_up_first_and_preserves_data(pg_url: URL, tmp_path: Path) -> None:
    original = Database.open(pg_url)
    with original.session() as session:
        session.add(Organization(name="Example Studio", normalized_name="example studio"))
    original.dispose()

    calls: list[tuple[str, str]] = []

    def backup(old: str, new: str) -> Path:
        calls.append((old, new))
        return tmp_path / "backup.dump"

    migrations = _extra_chain(tmp_path, "0099_test_column.py", EXTRA_REVISION)
    upgraded = Database.open(pg_url, migrations_dir=migrations, pre_upgrade_backup=backup)
    try:
        assert calls == [(HEAD, "0099")]
        assert upgraded.pre_migration_backup == tmp_path / "backup.dump"
        assert upgraded.schema_revision() == "0099"
        columns = {c["name"] for c in inspect(upgraded.engine).get_columns("organizations")}
        assert "test_column" in columns
        with upgraded.session() as session:
            assert session.scalars(select(Organization.name)).all() == ["Example Studio"]
    finally:
        upgraded.dispose()


def test_failed_upgrade_leaves_database_unchanged(pg_url: URL, tmp_path: Path) -> None:
    original = Database.open(pg_url)
    with original.session() as session:
        session.add(Organization(name="Keep Me", normalized_name="keep me"))
    original.dispose()

    migrations = _extra_chain(tmp_path, "0099_fails.py", FAILING_REVISION)
    with pytest.raises(MigrationError) as info:
        Database.open(
            pg_url,
            migrations_dir=migrations,
            pre_upgrade_backup=lambda _a, _b: tmp_path / "safety.dump",
        )
    assert "simulated migration failure" in str(info.value.detail)
    assert "Your data was not changed" in info.value.suggested_action
    assert "safety.dump" in info.value.suggested_action

    reopened = Database.open(pg_url)
    try:
        assert reopened.schema_revision() == HEAD
        with reopened.engine.connect() as connection:
            assert connection.scalar(text("SELECT name FROM organizations")) == "Keep Me"
        columns = {c["name"] for c in inspect(reopened.engine).get_columns("organizations")}
        assert "half_done" not in columns
        assert reopened.check_integrity(full=True).ok
    finally:
        reopened.dispose()


def test_database_from_newer_version_is_refused(pg_url: URL) -> None:
    engine = create_pg_engine(pg_url, pool_size=1)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = '9999'"))
    engine.dispose()
    with pytest.raises(DatabaseVersionError, match="newer version"):
        Database.open(pg_url)


def test_database_with_foreign_tables_is_refused(
    pg_server: PgTestServer, make_database: Callable[..., Database]
) -> None:
    url = pg_server.url_for("postgres")
    name = "tg_test_foreign"
    engine = create_pg_engine(url, pool_size=1)
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text(f"DROP DATABASE IF EXISTS {name}"))
        connection.execute(text(f"CREATE DATABASE {name}"))
    engine.dispose()
    foreign = pg_server.url_for(name)
    other = create_pg_engine(foreign, pool_size=1)
    with other.begin() as connection:
        connection.execute(text("CREATE TABLE invoices (id int)"))
    other.dispose()
    try:
        with pytest.raises(DatabaseCorruptError, match="do not belong"):
            Database.open(foreign)
    finally:
        pg_server.drop_database(foreign)


def test_unreachable_server_gives_actionable_error() -> None:
    with pytest.raises(DatabaseOpenError) as info:
        Database.open("postgresql://nobody:wrong@127.0.0.1:1/none")
    assert "launch.bat" in info.value.suggested_action


def test_wrong_password_gives_actionable_error(pg_url: URL) -> None:
    with pytest.raises(DatabaseOpenError, match="sign in"):
        Database.open(pg_url.set(password="definitely-wrong"))


def test_integrity_check_passes_and_detects_missing_trigger(database: Database) -> None:
    assert database.check_integrity(full=True).ok
    with database.engine.begin() as connection:
        connection.execute(text("DROP TRIGGER trg_activities_immutable ON activities"))
    report = database.check_integrity()
    assert not report.ok
    assert any("immutability" in problem for problem in report.problems)


def test_unicode_text_round_trips(database: Database) -> None:
    name = "Données de vente ñ 販売 🎮"
    with database.session() as session:
        session.add(Organization(name=name, normalized_name="x"))
    with database.session() as session:
        assert session.scalars(select(Organization.name)).one() == name
