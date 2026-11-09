# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Initial schema: all tables, activity immutability triggers, default stages.

Revision ID: 0001
Revises:
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import tg_sales.db.types

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Built-in rows are identical on every computer so sync never duplicates them.
SYSTEM_DEVICE_ID = "00000000-0000-0000-0000-000000000000"
SEED_TIMESTAMP = "2026-01-01T00:00:00.000000Z"
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


def upgrade() -> None:
    op.create_table(
        "actors",
        sa.Column("display_name", sa.Text(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_actors")),
    )
    with op.batch_alter_table("actors", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_actors_updated_at_utc"), ["updated_at_utc"], unique=False
        )

    op.create_table(
        "discovery_runs",
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("parameters", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("finished_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("result_count", sa.Integer(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_runs")),
    )
    with op.batch_alter_table("discovery_runs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_discovery_runs_updated_at_utc"), ["updated_at_utc"], unique=False
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
        sa.Column("discovered_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_games")),
    )
    with op.batch_alter_table("games", schema=None) as batch_op:
        batch_op.create_index("ix_games_release_date", ["release_date"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_games_updated_at_utc"), ["updated_at_utc"], unique=False
        )
        batch_op.create_index(
            "uq_games_store_store_id",
            ["store", "store_id"],
            unique=True,
            sqlite_where=sa.text("deleted_at_utc IS NULL AND store_id IS NOT NULL"),
        )

    op.create_table(
        "import_jobs",
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("file_size_bytes", sa.Integer(), nullable=False),
        sa.Column("file_type", sa.String(length=16), nullable=False),
        sa.Column("sheet_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("finished_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("created_count", sa.Integer(), nullable=False),
        sa.Column("updated_count", sa.Integer(), nullable=False),
        sa.Column("skipped_count", sa.Integer(), nullable=False),
        sa.Column("error_count", sa.Integer(), nullable=False),
        sa.Column("mapping", sa.JSON(), nullable=False),
        sa.Column("error_summary", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_jobs")),
    )
    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_import_jobs_file_sha256"), ["file_sha256"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_import_jobs_updated_at_utc"), ["updated_at_utc"], unique=False
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
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_organizations")),
    )
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.create_index("ix_organizations_created_at_utc", ["created_at_utc"], unique=False)
        batch_op.create_index(batch_op.f("ix_organizations_domain"), ["domain"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_organizations_normalized_name"), ["normalized_name"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_organizations_updated_at_utc"), ["updated_at_utc"], unique=False
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
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pipeline_stages")),
    )
    with op.batch_alter_table("pipeline_stages", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_pipeline_stages_updated_at_utc"), ["updated_at_utc"], unique=False
        )

    op.create_table(
        "settings",
        sa.Column("key", sa.String(length=128), nullable=False),
        sa.Column(
            "scope",
            sa.Enum("shared", "device", name="settingscope", native_enum=False, length=32),
            nullable=False,
        ),
        sa.Column("value", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_settings")),
    )
    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_settings_updated_at_utc"), ["updated_at_utc"], unique=False
        )
        batch_op.create_index(
            "uq_settings_key_scope",
            ["key", "scope"],
            unique=True,
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
        )

    op.create_table(
        "snapshots",
        sa.Column("relative_path", sa.Text(), nullable=False),
        sa.Column("filters", sa.JSON(), nullable=False),
        sa.Column("generated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=False),
        sa.Column("width_px", sa.Integer(), nullable=True),
        sa.Column("height_px", sa.Integer(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_snapshots")),
    )
    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_snapshots_updated_at_utc"), ["updated_at_utc"], unique=False
        )

    op.create_table(
        "sync_exports",
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("watermark", sa.JSON(), nullable=False),
        sa.Column("record_count", sa.Integer(), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False),
        sa.Column("encrypted", sa.Boolean(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_exports")),
    )
    with op.batch_alter_table("sync_exports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_sync_exports_updated_at_utc"), ["updated_at_utc"], unique=False
        )

    op.create_table(
        "sync_imports",
        sa.Column("export_id", sa.String(length=36), nullable=False),
        sa.Column("source_device_id", sa.String(length=36), nullable=False),
        sa.Column("file_name", sa.Text(), nullable=False),
        sa.Column("file_sha256", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("imported_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("counts", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sync_imports")),
    )
    with op.batch_alter_table("sync_imports", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_sync_imports_updated_at_utc"), ["updated_at_utc"], unique=False
        )
        batch_op.create_index(
            "uq_sync_imports_export_id",
            ["export_id"],
            unique=True,
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
        )

    op.create_table(
        "conflicts",
        sa.Column("sync_import_id", sa.String(length=36), nullable=True),
        sa.Column("entity_table", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("field", sa.String(length=64), nullable=True),
        sa.Column("local_value", sa.JSON(), nullable=True),
        sa.Column("incoming_value", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("resolution", sa.String(length=32), nullable=True),
        sa.Column("resolved_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("resolved_by_actor_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["resolved_by_actor_id"],
            ["actors.id"],
            name=op.f("fk_conflicts_resolved_by_actor_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["sync_import_id"],
            ["sync_imports.id"],
            name=op.f("fk_conflicts_sync_import_id_sync_imports"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_conflicts")),
    )
    with op.batch_alter_table("conflicts", schema=None) as batch_op:
        batch_op.create_index(
            "ix_conflicts_entity_table_entity_id", ["entity_table", "entity_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_conflicts_resolved_by_actor_id"), ["resolved_by_actor_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_conflicts_sync_import_id"), ["sync_import_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_conflicts_updated_at_utc"), ["updated_at_utc"], unique=False
        )

    op.create_table(
        "contacts",
        sa.Column("organization_id", sa.String(length=36), nullable=False),
        sa.Column("name", sa.Text(), nullable=True),
        sa.Column("role_title", sa.Text(), nullable=True),
        sa.Column("business_email", sa.Text(), nullable=True),
        sa.Column("email_normalized", sa.Text(), nullable=True),
        sa.Column("social_urls", sa.JSON(), nullable=False),
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
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_contacts_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_contacts")),
    )
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.create_index("ix_contacts_created_at_utc", ["created_at_utc"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_contacts_email_normalized"), ["email_normalized"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_contacts_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_contacts_updated_at_utc"), ["updated_at_utc"], unique=False
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
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name=op.f("fk_game_organizations_game_id_games")
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_game_organizations_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_game_organizations")),
    )
    with op.batch_alter_table("game_organizations", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_game_organizations_game_id"), ["game_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_game_organizations_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_game_organizations_updated_at_utc"), ["updated_at_utc"], unique=False
        )
        batch_op.create_index(
            "uq_game_organizations_game_id_organization_id_role",
            ["game_id", "organization_id", "role"],
            unique=True,
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
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
        sa.Column("next_action_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("next_action_note", sa.Text(), nullable=True),
        sa.Column("outcome_reason", sa.Text(), nullable=True),
        sa.Column("closed_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
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
        ),
        sa.ForeignKeyConstraint(
            ["owner_actor_id"], ["actors.id"], name=op.f("fk_opportunities_owner_actor_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["stage_id"],
            ["pipeline_stages.id"],
            name=op.f("fk_opportunities_stage_id_pipeline_stages"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_opportunities")),
    )
    with op.batch_alter_table("opportunities", schema=None) as batch_op:
        batch_op.create_index(
            "ix_opportunities_next_action_at_utc", ["next_action_at_utc"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_opportunities_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_opportunities_owner_actor_id"), ["owner_actor_id"], unique=False
        )
        batch_op.create_index("ix_opportunities_product_lane", ["product_lane"], unique=False)
        batch_op.create_index(batch_op.f("ix_opportunities_stage_id"), ["stage_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_opportunities_updated_at_utc"), ["updated_at_utc"], unique=False
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
        sa.Column("tags", sa.JSON(), nullable=False),
        sa.Column("is_favorite", sa.Boolean(), nullable=False),
        sa.Column("is_approved", sa.Boolean(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["author_actor_id"],
            ["actors.id"],
            name=op.f("fk_playbook_templates_author_actor_id_actors"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_templates")),
    )
    with op.batch_alter_table("playbook_templates", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_playbook_templates_author_actor_id"), ["author_actor_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_playbook_templates_updated_at_utc"), ["updated_at_utc"], unique=False
        )

    op.create_table(
        "activities",
        sa.Column("occurred_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column(
            "type",
            sa.Enum(
                "opportunity_created",
                "stage_change",
                "field_change",
                "correction",
                "note",
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
        sa.Column("payload", sa.JSON(), nullable=False),
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
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["actor_id"], ["actors.id"], name=op.f("fk_activities_actor_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_activities_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["corrects_event_id"],
            ["activities.id"],
            name=op.f("fk_activities_corrects_event_id_activities"),
        ),
        sa.ForeignKeyConstraint(
            ["game_id"], ["games.id"], name=op.f("fk_activities_game_id_games")
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_activities_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_activities_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_activities")),
    )
    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_activities_actor_id"), ["actor_id"], unique=False)
        batch_op.create_index(batch_op.f("ix_activities_contact_id"), ["contact_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_activities_corrects_event_id"), ["corrects_event_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_activities_game_id"), ["game_id"], unique=False)
        batch_op.create_index("ix_activities_occurred_at_utc", ["occurred_at_utc"], unique=False)
        batch_op.create_index(
            "ix_activities_opportunity_id_occurred_at_utc",
            ["opportunity_id", "occurred_at_utc"],
            unique=False,
        )
        batch_op.create_index(
            batch_op.f("ix_activities_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            "ix_activities_type_occurred_at_utc", ["type", "occurred_at_utc"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_activities_updated_at_utc"), ["updated_at_utc"], unique=False
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
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["contact_id"], ["contacts.id"], name=op.f("fk_attachments_contact_id_contacts")
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_attachments_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_attachments_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_attachments")),
    )
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.create_index(batch_op.f("ix_attachments_contact_id"), ["contact_id"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_attachments_opportunity_id"), ["opportunity_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attachments_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_attachments_updated_at_utc"), ["updated_at_utc"], unique=False
        )

    for operation in ("UPDATE", "DELETE"):
        op.execute(
            f"CREATE TRIGGER trg_activities_no_{operation.lower()} "
            f"BEFORE {operation} ON activities "
            "BEGIN SELECT RAISE(ABORT, 'activities are immutable'); END"
        )

    stages = sa.table(
        "pipeline_stages",
        sa.column("id", sa.String),
        sa.column("name", sa.Text),
        sa.column("sort_order", sa.Integer),
        sa.column("product_lane", sa.String),
        sa.column("outcome", sa.String),
        sa.column("archived_at_utc", sa.String),
        sa.column("created_at_utc", sa.String),
        sa.column("updated_at_utc", sa.String),
        sa.column("created_by_device_id", sa.String),
        sa.column("deleted_at_utc", sa.String),
    )
    op.bulk_insert(
        stages,
        [
            {
                "id": stage_id,
                "name": name,
                "sort_order": sort_order,
                "product_lane": None,
                "outcome": outcome,
                "archived_at_utc": None,
                "created_at_utc": SEED_TIMESTAMP,
                "updated_at_utc": SEED_TIMESTAMP,
                "created_by_device_id": SYSTEM_DEVICE_ID,
                "deleted_at_utc": None,
            }
            for stage_id, name, sort_order, outcome in DEFAULT_STAGES
        ],
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS trg_activities_no_update")
    op.execute("DROP TRIGGER IF EXISTS trg_activities_no_delete")
    with op.batch_alter_table("attachments", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_attachments_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_attachments_organization_id"))
        batch_op.drop_index(batch_op.f("ix_attachments_opportunity_id"))
        batch_op.drop_index(batch_op.f("ix_attachments_contact_id"))

    op.drop_table("attachments")
    with op.batch_alter_table("activities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_activities_updated_at_utc"))
        batch_op.drop_index("ix_activities_type_occurred_at_utc")
        batch_op.drop_index(batch_op.f("ix_activities_organization_id"))
        batch_op.drop_index("ix_activities_opportunity_id_occurred_at_utc")
        batch_op.drop_index("ix_activities_occurred_at_utc")
        batch_op.drop_index(batch_op.f("ix_activities_game_id"))
        batch_op.drop_index(batch_op.f("ix_activities_corrects_event_id"))
        batch_op.drop_index(batch_op.f("ix_activities_contact_id"))
        batch_op.drop_index(batch_op.f("ix_activities_actor_id"))

    op.drop_table("activities")
    with op.batch_alter_table("playbook_templates", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_playbook_templates_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_playbook_templates_author_actor_id"))

    op.drop_table("playbook_templates")
    with op.batch_alter_table("opportunities", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_opportunities_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_opportunities_stage_id"))
        batch_op.drop_index("ix_opportunities_product_lane")
        batch_op.drop_index(batch_op.f("ix_opportunities_owner_actor_id"))
        batch_op.drop_index(batch_op.f("ix_opportunities_organization_id"))
        batch_op.drop_index("ix_opportunities_next_action_at_utc")

    op.drop_table("opportunities")
    with op.batch_alter_table("game_organizations", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_game_organizations_game_id_organization_id_role",
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
        )
        batch_op.drop_index(batch_op.f("ix_game_organizations_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_game_organizations_organization_id"))
        batch_op.drop_index(batch_op.f("ix_game_organizations_game_id"))

    op.drop_table("game_organizations")
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_contacts_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_contacts_organization_id"))
        batch_op.drop_index(batch_op.f("ix_contacts_email_normalized"))
        batch_op.drop_index("ix_contacts_created_at_utc")

    op.drop_table("contacts")
    with op.batch_alter_table("conflicts", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_conflicts_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_conflicts_sync_import_id"))
        batch_op.drop_index(batch_op.f("ix_conflicts_resolved_by_actor_id"))
        batch_op.drop_index("ix_conflicts_entity_table_entity_id")

    op.drop_table("conflicts")
    with op.batch_alter_table("sync_imports", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_sync_imports_export_id", sqlite_where=sa.text("deleted_at_utc IS NULL")
        )
        batch_op.drop_index(batch_op.f("ix_sync_imports_updated_at_utc"))

    op.drop_table("sync_imports")
    with op.batch_alter_table("sync_exports", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_sync_exports_updated_at_utc"))

    op.drop_table("sync_exports")
    with op.batch_alter_table("snapshots", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_snapshots_updated_at_utc"))

    op.drop_table("snapshots")
    with op.batch_alter_table("settings", schema=None) as batch_op:
        batch_op.drop_index("uq_settings_key_scope", sqlite_where=sa.text("deleted_at_utc IS NULL"))
        batch_op.drop_index(batch_op.f("ix_settings_updated_at_utc"))

    op.drop_table("settings")
    with op.batch_alter_table("pipeline_stages", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_pipeline_stages_updated_at_utc"))

    op.drop_table("pipeline_stages")
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_organizations_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_organizations_normalized_name"))
        batch_op.drop_index(batch_op.f("ix_organizations_domain"))
        batch_op.drop_index("ix_organizations_created_at_utc")

    op.drop_table("organizations")
    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_import_jobs_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_import_jobs_file_sha256"))

    op.drop_table("import_jobs")
    with op.batch_alter_table("games", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_games_store_store_id",
            sqlite_where=sa.text("deleted_at_utc IS NULL AND store_id IS NOT NULL"),
        )
        batch_op.drop_index(batch_op.f("ix_games_updated_at_utc"))
        batch_op.drop_index("ix_games_release_date")

    op.drop_table("games")
    with op.batch_alter_table("discovery_runs", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_discovery_runs_updated_at_utc"))

    op.drop_table("discovery_runs")
    with op.batch_alter_table("actors", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_actors_updated_at_utc"))

    op.drop_table("actors")
