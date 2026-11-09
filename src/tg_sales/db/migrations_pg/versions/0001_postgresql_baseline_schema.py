# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""PostgreSQL baseline schema.

All tables, partial unique indexes, deferrable foreign keys, the activity
immutability guard, the change-log triggers used by offline sync, and the
default pipeline stages (same deterministic ids as every other installation).

Revision ID: 0001
Revises:
Create Date: 2026-10-26 14:31:45.479697
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import tg_sales.db.types

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_DEVICE_ID = "00000000-0000-0000-0000-000000000000"
# The synchronized tables as they existed at this revision. Frozen here (not
# imported from the models) so later revisions that add synchronized tables do
# not change what this baseline creates.
SYNCED_TABLES: tuple[str, ...] = (
    "actors",
    "organizations",
    "contacts",
    "games",
    "game_organizations",
    "pipeline_stages",
    "opportunities",
    "tasks",
    "activities",
    "playbook_templates",
    "playbook_revisions",
    "playbook_outcomes",
    "settings",
    "resource_links",
)
SEED_TIMESTAMP = datetime(2026, 1, 1, tzinfo=UTC)
# (id, name, sort_order, outcome); ids are uuid5(TG_SALES_NAMESPACE, "pipeline_stage:<key>").
DEFAULT_STAGES = [
    ("8e93899e-103a-5fbb-b145-2a466cc22eb9", "Discovered", 10, "open"),
    ("27657138-1b67-5ebb-9e55-60a3b3c22087", "Researching", 20, "open"),
    ("4ca22897-2e79-56a1-9f66-3de483507a40", "Contacted", 30, "open"),
    ("ffe9f7c9-3f85-5570-b376-6037a8aa3eb8", "Follow-Up", 40, "open"),
    ("5cc338dd-dcc6-5d72-92b8-7fd30a8885da", "Interested", 50, "open"),
    ("c53cb55f-9b43-5de9-9447-10f437c16ad1", "Technical Review", 60, "open"),
    ("a9f4572e-4bcc-567a-b22e-f719447f8fcf", "Negotiation", 70, "open"),
    ("8ef45198-136d-5ee0-a87e-8d72c12f516d", "Won", 80, "won"),
    ("b2355c7b-ca40-5ab9-a0f3-367fc4a706b8", "Lost", 90, "lost"),
    ("d01a1b2e-e892-5abc-8fd3-e8dc6ba2ba2b", "Not a Fit", 100, "not_a_fit"),
]

IMMUTABLE_FUNCTION = """
CREATE FUNCTION tg_activities_immutable() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'activities are immutable'
        USING ERRCODE = 'integrity_constraint_violation';
END
$$
"""

# Records every insert/update of a synchronized row. A sync import sets
# tg_sales.applying_change_id so the incoming change keeps its original id.
CHANGE_FUNCTION = """
CREATE FUNCTION tg_record_change() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE
    applied text := nullif(current_setting('tg_sales.applying_change_id', true), '');
    device text := nullif(current_setting('tg_sales.device_id', true), '');
BEGIN
    IF TG_TABLE_NAME = 'settings' THEN
        IF NEW.scope <> 'shared' THEN
            RETURN NULL;
        END IF;
    END IF;
    IF TG_TABLE_NAME = 'resource_links' THEN
        IF NEW.kind <> 'link' THEN
            RETURN NULL;
        END IF;
    END IF;
    IF TG_OP = 'UPDATE' THEN
        IF NEW IS NOT DISTINCT FROM OLD THEN
            RETURN NULL;
        END IF;
    END IF;
    INSERT INTO change_log (entity_table, entity_id, change_id, device_id, origin, changed_at_utc)
    VALUES (
        TG_TABLE_NAME,
        NEW.id,
        coalesce(applied, gen_random_uuid()::text),
        device,
        CASE WHEN applied IS NULL THEN 'local' ELSE 'sync' END,
        clock_timestamp()
    )
    ON CONFLICT (entity_table, entity_id, change_id) DO NOTHING;
    RETURN NULL;
END
$$
"""


def upgrade() -> None:
    op.create_table(
        "actors",
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actors")),
    )
    op.create_index(op.f("ix_actors_updated_at_utc"), "actors", ["updated_at_utc"], unique=False)
    op.create_table(
        "change_log",
        sa.Column("seq", sa.BigInteger(), sa.Identity(always=False), nullable=False),
        sa.Column("entity_table", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("change_id", sa.String(length=36), nullable=False),
        sa.Column("device_id", sa.String(length=36), nullable=True),
        sa.Column("origin", sa.String(length=8), nullable=False),
        sa.Column("changed_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.PrimaryKeyConstraint("seq", name=op.f("pk_change_log")),
    )
    op.create_index(
        "ix_change_log_entity_table_entity_id_seq",
        "change_log",
        ["entity_table", "entity_id", "seq"],
        unique=False,
    )
    op.create_index(
        "uq_change_log_entity_table_entity_id_change_id",
        "change_log",
        ["entity_table", "entity_id", "change_id"],
        unique=True,
    )
    op.create_table(
        "discovery_runs",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column(
            "parameters",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("finished_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_runs")),
    )
    op.create_index(
        op.f("ix_discovery_runs_updated_at_utc"), "discovery_runs", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "games",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("store", sa.Text(), nullable=True),
        sa.Column("store_id", sa.Text(), nullable=True),
        sa.Column("store_url", sa.Text(), nullable=True),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column(
            "release_precision",
            sa.Enum(
                "day",
                "month",
                "quarter",
                "year",
                "unknown",
                name="releaseprecision",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "import",
                "discovery",
                "sync",
                "system",
                name="recordsource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("discovered_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_games")),
    )
    op.create_index("ix_games_release_date", "games", ["release_date"], unique=False)
    op.create_index(op.f("ix_games_updated_at_utc"), "games", ["updated_at_utc"], unique=False)
    op.create_index(
        "uq_games_store_store_id",
        "games",
        ["store", "store_id"],
        unique=True,
        sqlite_where=sa.text("deleted_at_utc IS NULL AND store_id IS NOT NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL AND store_id IS NOT NULL"),
    )
    op.create_table(
        "import_jobs",
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("sheet_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("finished_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("warning_count", sa.Integer(), nullable=False),
        sa.Column(
            "mapping",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("undone_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_jobs")),
    )
    op.create_index(
        op.f("ix_import_jobs_file_sha256"), "import_jobs", ["file_sha256"], unique=False
    )
    op.create_index(
        op.f("ix_import_jobs_updated_at_utc"), "import_jobs", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "organizations",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("normalized_name", sa.Text(), nullable=False),
        sa.Column("website", sa.Text(), nullable=True),
        sa.Column("domain", sa.Text(), nullable=True),
        sa.Column("location", sa.Text(), nullable=True),
        sa.Column("country", sa.Text(), nullable=True),
        sa.Column(
            "company_type",
            sa.Enum(
                "unknown",
                "studio",
                "publisher",
                "data_buyer",
                "other",
                name="organizationtype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "import",
                "discovery",
                "sync",
                "system",
                name="recordsource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column(
            "tags",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    op.create_index(
        "ix_organizations_created_at_utc", "organizations", ["created_at_utc"], unique=False
    )
    op.create_index(op.f("ix_organizations_domain"), "organizations", ["domain"], unique=False)
    op.create_index(
        op.f("ix_organizations_normalized_name"), "organizations", ["normalized_name"], unique=False
    )
    op.create_index(
        op.f("ix_organizations_updated_at_utc"), "organizations", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "pipeline_stages",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column(
            "product_lane",
            sa.Enum(
                "data_licensing",
                "publisher_partnership",
                "mikros_marketing",
                name="productlane",
                native_enum=False,
                length=32,
            ),
            nullable=True,
        ),
        sa.Column(
            "outcome",
            sa.Enum(
                "open",
                "won",
                "lost",
                "not_a_fit",
                name="stageoutcome",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_stages")),
    )
    op.create_index(
        op.f("ix_pipeline_stages_updated_at_utc"),
        "pipeline_stages",
        ["updated_at_utc"],
        unique=False,
    )
    op.create_table(
        "resource_links",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("kind", sa.String(length=16), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_resource_links")),
    )
    op.create_index(
        op.f("ix_resource_links_updated_at_utc"), "resource_links", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column(
            "scope",
            sa.Enum("shared", "device", name="settingscope", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column(
            "value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
    )
    op.create_index(
        op.f("ix_settings_updated_at_utc"), "settings", ["updated_at_utc"], unique=False
    )
    op.create_index(
        "uq_settings_key_scope",
        "settings",
        ["key", "scope"],
        unique=True,
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.create_table(
        "snapshots",
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column(
            "filters",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("generated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
    )
    op.create_index(
        op.f("ix_snapshots_updated_at_utc"), "snapshots", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "sync_exports",
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column(
            "watermark",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_exports")),
    )
    op.create_index(
        op.f("ix_sync_exports_updated_at_utc"), "sync_exports", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "sync_imports",
        sa.Column("export_id", sa.String(length=36), nullable=False),
        sa.Column("source_device_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("imported_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column(
            "counts",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_imports")),
    )
    op.create_index(
        op.f("ix_sync_imports_updated_at_utc"), "sync_imports", ["updated_at_utc"], unique=False
    )
    op.create_index(
        "uq_sync_imports_export_id",
        "sync_imports",
        ["export_id"],
        unique=True,
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.create_table(
        "conflicts",
        sa.Column("sync_import_id", sa.String(length=36), nullable=True),
        sa.Column("entity_table", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=True),
        sa.Column(
            "local_value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column(
            "incoming_value",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=True,
        ),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("resolved_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("resolved_by_actor_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["resolved_by_actor_id"],
            ["actors.id"],
            name=op.f("fk_conflicts_resolved_by_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["sync_import_id"],
            ["sync_imports.id"],
            name=op.f("fk_conflicts_sync_import_id_sync_imports"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflicts")),
    )
    op.create_index(
        "ix_conflicts_entity_table_entity_id",
        "conflicts",
        ["entity_table", "entity_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conflicts_resolved_by_actor_id"),
        "conflicts",
        ["resolved_by_actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_conflicts_sync_import_id"), "conflicts", ["sync_import_id"], unique=False
    )
    op.create_index(
        op.f("ix_conflicts_updated_at_utc"), "conflicts", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "contacts",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("role_title", sa.Text(), nullable=True),
        sa.Column("business_email", sa.Text(), nullable=True),
        sa.Column("email_normalized", sa.Text(), nullable=True),
        sa.Column(
            "social_urls",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "contact_status",
            sa.Enum(
                "unknown",
                "not_contacted",
                "attempted",
                "responded",
                name="contactstatus",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("provenance", sa.Text(), nullable=True),
        sa.Column("source_url", sa.Text(), nullable=True),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "import",
                "discovery",
                "sync",
                "system",
                name="recordsource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_contacts_organization_id_organizations"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
    )
    op.create_index("ix_contacts_created_at_utc", "contacts", ["created_at_utc"], unique=False)
    op.create_index(
        op.f("ix_contacts_email_normalized"), "contacts", ["email_normalized"], unique=False
    )
    op.create_index(
        op.f("ix_contacts_organization_id"), "contacts", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_contacts_updated_at_utc"), "contacts", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "discovery_leads",
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column(
            "data",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("release_date", sa.Date(), nullable=True),
        sa.Column(
            "release_precision",
            sa.Enum(
                "day",
                "month",
                "quarter",
                "year",
                "unknown",
                name="releaseprecision",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("contact_status", sa.String(length=24), nullable=False),
        sa.Column("contact_email", sa.Text(), nullable=True),
        sa.Column("contact_source_url", sa.Text(), nullable=True),
        sa.Column("provenance_url", sa.Text(), nullable=False),
        sa.Column("last_checked_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_discovery_leads_organization_id_organizations"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["run_id"],
            ["discovery_runs.id"],
            name=op.f("fk_discovery_leads_run_id_discovery_runs"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_leads")),
    )
    op.create_index(
        op.f("ix_discovery_leads_organization_id"),
        "discovery_leads",
        ["organization_id"],
        unique=False,
    )
    op.create_index(op.f("ix_discovery_leads_run_id"), "discovery_leads", ["run_id"], unique=False)
    op.create_index("ix_discovery_leads_status", "discovery_leads", ["status"], unique=False)
    op.create_index(
        op.f("ix_discovery_leads_updated_at_utc"),
        "discovery_leads",
        ["updated_at_utc"],
        unique=False,
    )
    op.create_index(
        "uq_discovery_leads_source_external_id",
        "discovery_leads",
        ["source", "external_id"],
        unique=True,
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.create_table(
        "game_organizations",
        sa.Column("game_id", sa.String(length=36), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column(
            "role",
            sa.Enum("developer", "publisher", name="gamerole", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
            name=op.f("fk_game_organizations_game_id_games"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_game_organizations_organization_id_organizations"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game_organizations")),
    )
    op.create_index(
        op.f("ix_game_organizations_game_id"), "game_organizations", ["game_id"], unique=False
    )
    op.create_index(
        op.f("ix_game_organizations_organization_id"),
        "game_organizations",
        ["organization_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_game_organizations_updated_at_utc"),
        "game_organizations",
        ["updated_at_utc"],
        unique=False,
    )
    op.create_index(
        "uq_game_organizations_game_id_organization_id_role",
        "game_organizations",
        ["game_id", "organization_id", "role"],
        unique=True,
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.create_table(
        "import_changes",
        sa.Column("import_job_id", sa.String(length=36), nullable=False),
        sa.Column("entity_table", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("row_fingerprint", sa.String(length=64), nullable=True),
        sa.Column(
            "previous_values",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_job_id"],
            ["import_jobs.id"],
            name=op.f("fk_import_changes_import_job_id_import_jobs"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_changes")),
    )
    op.create_index(
        op.f("ix_import_changes_entity_id"), "import_changes", ["entity_id"], unique=False
    )
    op.create_index(
        op.f("ix_import_changes_import_job_id"), "import_changes", ["import_job_id"], unique=False
    )
    op.create_index(
        op.f("ix_import_changes_row_fingerprint"),
        "import_changes",
        ["row_fingerprint"],
        unique=False,
    )
    op.create_index(
        op.f("ix_import_changes_updated_at_utc"), "import_changes", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "opportunities",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column(
            "product_lane",
            sa.Enum(
                "data_licensing",
                "publisher_partnership",
                "mikros_marketing",
                name="productlane",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("stage_id", sa.String(length=36), nullable=False),
        sa.Column("owner_actor_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("estimated_value", sa.Float(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("probability", sa.Float(), nullable=True),
        sa.Column("next_action_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("next_action_note", sa.Text(), nullable=True),
        sa.Column("outcome_reason", sa.Text(), nullable=True),
        sa.Column("outcome_reason_code", sa.String(length=32), nullable=True),
        sa.Column("closed_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.CheckConstraint(
            "estimated_value IS NULL OR estimated_value >= 0",
            name=op.f("ck_opportunities_estimated_value_positive"),
        ),
        sa.CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 1)",
            name=op.f("ck_opportunities_probability_range"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_opportunities_organization_id_organizations"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["owner_actor_id"],
            ["actors.id"],
            name=op.f("fk_opportunities_owner_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["pipeline_stages.id"],
            name=op.f("fk_opportunities_stage_id_pipeline_stages"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
    )
    op.create_index(
        "ix_opportunities_next_action_at_utc", "opportunities", ["next_action_at_utc"], unique=False
    )
    op.create_index(
        op.f("ix_opportunities_organization_id"), "opportunities", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_opportunities_owner_actor_id"), "opportunities", ["owner_actor_id"], unique=False
    )
    op.create_index(
        "ix_opportunities_product_lane", "opportunities", ["product_lane"], unique=False
    )
    op.create_index(op.f("ix_opportunities_stage_id"), "opportunities", ["stage_id"], unique=False)
    op.create_index(
        op.f("ix_opportunities_updated_at_utc"), "opportunities", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "playbook_templates",
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("label", sa.Text(), nullable=True),
        sa.Column("category", sa.Text(), nullable=True),
        sa.Column("channel", sa.Text(), nullable=True),
        sa.Column("audience", sa.Text(), nullable=True),
        sa.Column("stage", sa.Text(), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("author_actor_id", sa.String(length=36), nullable=True),
        sa.Column(
            "tags",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("is_approved", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("example_key", sa.String(length=64), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_actor_id"],
            ["actors.id"],
            name=op.f("fk_playbook_templates_author_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_templates")),
    )
    op.create_index(
        op.f("ix_playbook_templates_author_actor_id"),
        "playbook_templates",
        ["author_actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playbook_templates_updated_at_utc"),
        "playbook_templates",
        ["updated_at_utc"],
        unique=False,
    )
    op.create_index(
        "uq_playbook_templates_example_key",
        "playbook_templates",
        ["example_key"],
        unique=True,
        sqlite_where=sa.text("deleted_at_utc IS NULL AND example_key IS NOT NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL AND example_key IS NOT NULL"),
    )
    op.create_table(
        "report_records",
        sa.Column("folder_name", sa.String(length=128), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column(
            "filters",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("generated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=True),
        sa.Column("has_html", sa.Boolean(), nullable=False),
        sa.Column(
            "totals",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("author_actor_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_actor_id"],
            ["actors.id"],
            name=op.f("fk_report_records_author_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_report_records")),
    )
    op.create_index(
        op.f("ix_report_records_author_actor_id"),
        "report_records",
        ["author_actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_report_records_updated_at_utc"), "report_records", ["updated_at_utc"], unique=False
    )
    op.create_index("uq_report_records_folder_name", "report_records", ["folder_name"], unique=True)
    op.create_table(
        "activities",
        sa.Column("occurred_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "opportunity_created",
                "stage_change",
                "field_change",
                "correction",
                "note",
                "organization_created",
                "import_committed",
                "import_undone",
                "task_created",
                "task_completed",
                "contacted",
                "email",
                "linkedin_invite",
                "linkedin_message",
                "phone_call",
                "meeting",
                "reply",
                "demo",
                "data_room_shared",
                "technical_handoff",
                "proposal",
                "won",
                "lost",
                "closed",
                name="activitytype",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("actor_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("opportunity_id", sa.String(length=36), nullable=True),
        sa.Column("game_id", sa.String(length=36), nullable=True),
        sa.Column("corrects_event_id", sa.String(length=36), nullable=True),
        sa.Column(
            "payload",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.Enum(
                "manual",
                "import",
                "discovery",
                "sync",
                "system",
                name="recordsource",
                native_enum=False,
                length=32,
            ),
            nullable=False,
        ),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"],
            ["actors.id"],
            name=op.f("fk_activities_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_activities_contact_id_contacts"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["corrects_event_id"],
            ["activities.id"],
            name=op.f("fk_activities_corrects_event_id_activities"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["game_id"],
            ["games.id"],
            name=op.f("fk_activities_game_id_games"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_activities_opportunity_id_opportunities"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_activities_organization_id_organizations"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activities")),
    )
    op.create_index(op.f("ix_activities_actor_id"), "activities", ["actor_id"], unique=False)
    op.create_index(op.f("ix_activities_contact_id"), "activities", ["contact_id"], unique=False)
    op.create_index(
        op.f("ix_activities_corrects_event_id"), "activities", ["corrects_event_id"], unique=False
    )
    op.create_index(op.f("ix_activities_game_id"), "activities", ["game_id"], unique=False)
    op.create_index(
        "ix_activities_occurred_at_utc", "activities", ["occurred_at_utc"], unique=False
    )
    op.create_index(
        "ix_activities_opportunity_id_occurred_at_utc",
        "activities",
        ["opportunity_id", "occurred_at_utc"],
        unique=False,
    )
    op.create_index(
        op.f("ix_activities_organization_id"), "activities", ["organization_id"], unique=False
    )
    op.create_index(
        "ix_activities_type_occurred_at_utc",
        "activities",
        ["type", "occurred_at_utc"],
        unique=False,
    )
    op.create_index(
        op.f("ix_activities_updated_at_utc"), "activities", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "attachments",
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("contact_id", sa.String(length=36), nullable=True),
        sa.Column("opportunity_id", sa.String(length=36), nullable=True),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("media_type", sa.String(length=128), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["contact_id"],
            ["contacts.id"],
            name=op.f("fk_attachments_contact_id_contacts"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_attachments_opportunity_id_opportunities"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_attachments_organization_id_organizations"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    op.create_index(op.f("ix_attachments_contact_id"), "attachments", ["contact_id"], unique=False)
    op.create_index(
        op.f("ix_attachments_opportunity_id"), "attachments", ["opportunity_id"], unique=False
    )
    op.create_index(
        op.f("ix_attachments_organization_id"), "attachments", ["organization_id"], unique=False
    )
    op.create_index(
        op.f("ix_attachments_updated_at_utc"), "attachments", ["updated_at_utc"], unique=False
    )
    op.create_table(
        "playbook_outcomes",
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("author_actor_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_actor_id"],
            ["actors.id"],
            name=op.f("fk_playbook_outcomes_author_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["playbook_templates.id"],
            name=op.f("fk_playbook_outcomes_template_id_playbook_templates"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_outcomes")),
    )
    op.create_index(
        op.f("ix_playbook_outcomes_author_actor_id"),
        "playbook_outcomes",
        ["author_actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playbook_outcomes_template_id"), "playbook_outcomes", ["template_id"], unique=False
    )
    op.create_index(
        op.f("ix_playbook_outcomes_updated_at_utc"),
        "playbook_outcomes",
        ["updated_at_utc"],
        unique=False,
    )
    op.create_table(
        "playbook_revisions",
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column(
            "content",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("author_actor_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_actor_id"],
            ["actors.id"],
            name=op.f("fk_playbook_revisions_author_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["playbook_templates.id"],
            name=op.f("fk_playbook_revisions_template_id_playbook_templates"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_revisions")),
    )
    op.create_index(
        op.f("ix_playbook_revisions_author_actor_id"),
        "playbook_revisions",
        ["author_actor_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playbook_revisions_template_id"),
        "playbook_revisions",
        ["template_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_playbook_revisions_updated_at_utc"),
        "playbook_revisions",
        ["updated_at_utc"],
        unique=False,
    )
    op.create_index(
        "uq_playbook_revisions_template_id_revision",
        "playbook_revisions",
        ["template_id", "revision"],
        unique=True,
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.create_table(
        "tasks",
        sa.Column("opportunity_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("assignee_actor_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("completed_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        sa.ForeignKeyConstraint(
            ["assignee_actor_id"],
            ["actors.id"],
            name=op.f("fk_tasks_assignee_actor_id_actors"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_tasks_opportunity_id_opportunities"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_tasks_organization_id_organizations"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    op.create_index(
        op.f("ix_tasks_assignee_actor_id"), "tasks", ["assignee_actor_id"], unique=False
    )
    op.create_index("ix_tasks_due_at_utc", "tasks", ["due_at_utc"], unique=False)
    op.create_index(op.f("ix_tasks_opportunity_id"), "tasks", ["opportunity_id"], unique=False)
    op.create_index(op.f("ix_tasks_organization_id"), "tasks", ["organization_id"], unique=False)
    op.create_index(op.f("ix_tasks_updated_at_utc"), "tasks", ["updated_at_utc"], unique=False)

    op.create_table(
        "sync_pending",
        sa.Column("sync_import_id", sa.String(length=36), nullable=True),
        sa.Column("entity_table", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("change_id", sa.String(length=36), nullable=False),
        sa.Column(
            "record",
            sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql"),
            nullable=False,
        ),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["sync_import_id"],
            ["sync_imports.id"],
            name=op.f("fk_sync_pending_sync_import_id_sync_imports"),
            initially="IMMEDIATE",
            deferrable=True,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_pending")),
    )
    op.create_index(
        "uq_sync_pending_entity_table_entity_id_change_id",
        "sync_pending",
        ["entity_table", "entity_id", "change_id"],
        unique=True,
    )
    op.create_index(
        op.f("ix_sync_pending_sync_import_id"), "sync_pending", ["sync_import_id"], unique=False
    )
    op.create_index(
        op.f("ix_sync_pending_updated_at_utc"), "sync_pending", ["updated_at_utc"], unique=False
    )

    stages = sa.table(
        "pipeline_stages",
        sa.column("id", sa.String),
        sa.column("name", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("product_lane", sa.String),
        sa.column("outcome", sa.String),
        sa.column("created_at_utc", sa.DateTime(timezone=True)),
        sa.column("updated_at_utc", sa.DateTime(timezone=True)),
        sa.column("created_by_device_id", sa.String),
    )
    # Seeded before the change-log triggers exist: identical on every computer.
    op.bulk_insert(
        stages,
        [
            {
                "id": stage_id,
                "name": name,
                "sort_order": sort_order,
                "product_lane": None,
                "outcome": outcome,
                "created_at_utc": SEED_TIMESTAMP,
                "updated_at_utc": SEED_TIMESTAMP,
                "created_by_device_id": SYSTEM_DEVICE_ID,
            }
            for stage_id, name, sort_order, outcome in DEFAULT_STAGES
        ],
    )

    op.execute(IMMUTABLE_FUNCTION)
    op.execute(
        "CREATE TRIGGER trg_activities_immutable BEFORE UPDATE OR DELETE ON activities "
        "FOR EACH ROW EXECUTE FUNCTION tg_activities_immutable()"
    )
    op.execute(
        "CREATE TRIGGER trg_activities_no_truncate BEFORE TRUNCATE ON activities "
        "FOR EACH STATEMENT EXECUTE FUNCTION tg_activities_immutable()"
    )
    op.execute(CHANGE_FUNCTION)
    for table in SYNCED_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_change_log AFTER INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION tg_record_change()"
        )


def downgrade() -> None:
    for table in SYNCED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_change_log ON {table}")
    op.drop_table("sync_pending")
    op.execute("DROP TRIGGER IF EXISTS trg_activities_immutable ON activities")
    op.execute("DROP TRIGGER IF EXISTS trg_activities_no_truncate ON activities")
    op.execute("DROP FUNCTION IF EXISTS tg_record_change()")
    op.execute("DROP FUNCTION IF EXISTS tg_activities_immutable()")
    op.drop_index(op.f("ix_tasks_updated_at_utc"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_organization_id"), table_name="tasks")
    op.drop_index(op.f("ix_tasks_opportunity_id"), table_name="tasks")
    op.drop_index("ix_tasks_due_at_utc", table_name="tasks")
    op.drop_index(op.f("ix_tasks_assignee_actor_id"), table_name="tasks")
    op.drop_table("tasks")
    op.drop_index(
        "uq_playbook_revisions_template_id_revision",
        table_name="playbook_revisions",
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.drop_index(op.f("ix_playbook_revisions_updated_at_utc"), table_name="playbook_revisions")
    op.drop_index(op.f("ix_playbook_revisions_template_id"), table_name="playbook_revisions")
    op.drop_index(op.f("ix_playbook_revisions_author_actor_id"), table_name="playbook_revisions")
    op.drop_table("playbook_revisions")
    op.drop_index(op.f("ix_playbook_outcomes_updated_at_utc"), table_name="playbook_outcomes")
    op.drop_index(op.f("ix_playbook_outcomes_template_id"), table_name="playbook_outcomes")
    op.drop_index(op.f("ix_playbook_outcomes_author_actor_id"), table_name="playbook_outcomes")
    op.drop_table("playbook_outcomes")
    op.drop_index(op.f("ix_attachments_updated_at_utc"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_organization_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_opportunity_id"), table_name="attachments")
    op.drop_index(op.f("ix_attachments_contact_id"), table_name="attachments")
    op.drop_table("attachments")
    op.drop_index(op.f("ix_activities_updated_at_utc"), table_name="activities")
    op.drop_index("ix_activities_type_occurred_at_utc", table_name="activities")
    op.drop_index(op.f("ix_activities_organization_id"), table_name="activities")
    op.drop_index("ix_activities_opportunity_id_occurred_at_utc", table_name="activities")
    op.drop_index("ix_activities_occurred_at_utc", table_name="activities")
    op.drop_index(op.f("ix_activities_game_id"), table_name="activities")
    op.drop_index(op.f("ix_activities_corrects_event_id"), table_name="activities")
    op.drop_index(op.f("ix_activities_contact_id"), table_name="activities")
    op.drop_index(op.f("ix_activities_actor_id"), table_name="activities")
    op.drop_table("activities")
    op.drop_index("uq_report_records_folder_name", table_name="report_records")
    op.drop_index(op.f("ix_report_records_updated_at_utc"), table_name="report_records")
    op.drop_index(op.f("ix_report_records_author_actor_id"), table_name="report_records")
    op.drop_table("report_records")
    op.drop_index(
        "uq_playbook_templates_example_key",
        table_name="playbook_templates",
        sqlite_where=sa.text("deleted_at_utc IS NULL AND example_key IS NOT NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL AND example_key IS NOT NULL"),
    )
    op.drop_index(op.f("ix_playbook_templates_updated_at_utc"), table_name="playbook_templates")
    op.drop_index(op.f("ix_playbook_templates_author_actor_id"), table_name="playbook_templates")
    op.drop_table("playbook_templates")
    op.drop_index(op.f("ix_opportunities_updated_at_utc"), table_name="opportunities")
    op.drop_index(op.f("ix_opportunities_stage_id"), table_name="opportunities")
    op.drop_index("ix_opportunities_product_lane", table_name="opportunities")
    op.drop_index(op.f("ix_opportunities_owner_actor_id"), table_name="opportunities")
    op.drop_index(op.f("ix_opportunities_organization_id"), table_name="opportunities")
    op.drop_index("ix_opportunities_next_action_at_utc", table_name="opportunities")
    op.drop_table("opportunities")
    op.drop_index(op.f("ix_import_changes_updated_at_utc"), table_name="import_changes")
    op.drop_index(op.f("ix_import_changes_row_fingerprint"), table_name="import_changes")
    op.drop_index(op.f("ix_import_changes_import_job_id"), table_name="import_changes")
    op.drop_index(op.f("ix_import_changes_entity_id"), table_name="import_changes")
    op.drop_table("import_changes")
    op.drop_index(
        "uq_game_organizations_game_id_organization_id_role",
        table_name="game_organizations",
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.drop_index(op.f("ix_game_organizations_updated_at_utc"), table_name="game_organizations")
    op.drop_index(op.f("ix_game_organizations_organization_id"), table_name="game_organizations")
    op.drop_index(op.f("ix_game_organizations_game_id"), table_name="game_organizations")
    op.drop_table("game_organizations")
    op.drop_index(
        "uq_discovery_leads_source_external_id",
        table_name="discovery_leads",
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.drop_index(op.f("ix_discovery_leads_updated_at_utc"), table_name="discovery_leads")
    op.drop_index("ix_discovery_leads_status", table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_run_id"), table_name="discovery_leads")
    op.drop_index(op.f("ix_discovery_leads_organization_id"), table_name="discovery_leads")
    op.drop_table("discovery_leads")
    op.drop_index(op.f("ix_contacts_updated_at_utc"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_organization_id"), table_name="contacts")
    op.drop_index(op.f("ix_contacts_email_normalized"), table_name="contacts")
    op.drop_index("ix_contacts_created_at_utc", table_name="contacts")
    op.drop_table("contacts")
    op.drop_index(op.f("ix_conflicts_updated_at_utc"), table_name="conflicts")
    op.drop_index(op.f("ix_conflicts_sync_import_id"), table_name="conflicts")
    op.drop_index(op.f("ix_conflicts_resolved_by_actor_id"), table_name="conflicts")
    op.drop_index("ix_conflicts_entity_table_entity_id", table_name="conflicts")
    op.drop_table("conflicts")
    op.drop_index(
        "uq_sync_imports_export_id",
        table_name="sync_imports",
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.drop_index(op.f("ix_sync_imports_updated_at_utc"), table_name="sync_imports")
    op.drop_table("sync_imports")
    op.drop_index(op.f("ix_sync_exports_updated_at_utc"), table_name="sync_exports")
    op.drop_table("sync_exports")
    op.drop_index(op.f("ix_snapshots_updated_at_utc"), table_name="snapshots")
    op.drop_table("snapshots")
    op.drop_index(
        "uq_settings_key_scope",
        table_name="settings",
        sqlite_where=sa.text("deleted_at_utc IS NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL"),
    )
    op.drop_index(op.f("ix_settings_updated_at_utc"), table_name="settings")
    op.drop_table("settings")
    op.drop_index(op.f("ix_resource_links_updated_at_utc"), table_name="resource_links")
    op.drop_table("resource_links")
    op.drop_index(op.f("ix_pipeline_stages_updated_at_utc"), table_name="pipeline_stages")
    op.drop_table("pipeline_stages")
    op.drop_index(op.f("ix_organizations_updated_at_utc"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_normalized_name"), table_name="organizations")
    op.drop_index(op.f("ix_organizations_domain"), table_name="organizations")
    op.drop_index("ix_organizations_created_at_utc", table_name="organizations")
    op.drop_table("organizations")
    op.drop_index(op.f("ix_import_jobs_updated_at_utc"), table_name="import_jobs")
    op.drop_index(op.f("ix_import_jobs_file_sha256"), table_name="import_jobs")
    op.drop_table("import_jobs")
    op.drop_index(
        "uq_games_store_store_id",
        table_name="games",
        sqlite_where=sa.text("deleted_at_utc IS NULL AND store_id IS NOT NULL"),
        postgresql_where=sa.text("deleted_at_utc IS NULL AND store_id IS NOT NULL"),
    )
    op.drop_index(op.f("ix_games_updated_at_utc"), table_name="games")
    op.drop_index("ix_games_release_date", table_name="games")
    op.drop_table("games")
    op.drop_index(op.f("ix_discovery_runs_updated_at_utc"), table_name="discovery_runs")
    op.drop_table("discovery_runs")
    op.drop_index("uq_change_log_entity_table_entity_id_change_id", table_name="change_log")
    op.drop_index("ix_change_log_entity_table_entity_id_seq", table_name="change_log")
    op.drop_table("change_log")
    op.drop_index(op.f("ix_actors_updated_at_utc"), table_name="actors")
    op.drop_table("actors")
