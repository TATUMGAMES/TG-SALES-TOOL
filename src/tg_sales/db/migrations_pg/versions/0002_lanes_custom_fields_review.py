# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Configurable sales lanes, custom fields, review date and qualification source URL.

* ``sales_lanes``: the lanes that used to be built in. An existing
  installation (one that already holds prospects, opportunities, activity or
  lane-specific stages) keeps its original lanes (Data licensing, Publisher
  partnership, MIKROS Marketing) under their original keys, so every
  opportunity, stage and historical event keeps pointing at the same lane. A
  new installation starts with General Sales, Partnerships and Other.
  Any other lane key already in use is also given a lane, so nothing is left
  without one.
* ``custom_fields``: user-defined fields; their values are stored in the new
  ``custom_fields`` JSON column of ``organizations`` and ``contacts``.
* ``organizations.reviewed_on`` and ``organizations.qualification_source_url``.

No existing row is changed or removed. Seeded lanes are written before the
change-log triggers exist, like the default stages, so every computer gets the
same records without sync traffic.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-08
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

import tg_sales.db.types

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SYSTEM_DEVICE_ID = "00000000-0000-0000-0000-000000000000"
SEED_TIMESTAMP = datetime(2026, 11, 1, tzinfo=UTC)
# Same namespace as tg_sales.domain.ids (kept literal: migrations never import app logic
# that may change later).
NAMESPACE = uuid.UUID("5f0b6d0e-8c1a-4c3e-9a57-3b0d2f9c7e41")
NEW_SYNCED_TABLES = ("sales_lanes", "custom_fields")

# (key, name, color, description, technical_handoff)
Lane = tuple[str, str, str | None, str | None, bool]
TATUM_GAMES_LANES: list[Lane] = [
    (
        "data_licensing",
        "Data licensing",
        "#86c4c2",
        "Licensing game-market data to buyers.",
        True,
    ),
    (
        "publisher_partnership",
        "Publisher partnership",
        "#a787bd",
        "Publishing and co-development partnerships with studios.",
        False,
    ),
    (
        "mikros_marketing",
        "MIKROS Marketing",
        "#f6d271",
        "MIKROS Marketing services for studios.",
        False,
    ),
]
GENERIC_LANES: list[Lane] = [
    ("general_sales", "General Sales", "#a787bd", "Direct sales to customers.", False),
    ("partnerships", "Partnerships", "#86c4c2", "Partners, resellers and alliances.", False),
    ("other", "Other", "#c7d47f", "Anything that does not fit another lane.", False),
]


def _bookkeeping() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
    ]


def _lanes_to_seed(
    connection: sa.engine.Connection,
) -> list[tuple[str, str, str | None, str | None, bool]]:
    existing_installation = connection.scalar(
        sa.text(
            "SELECT EXISTS (SELECT 1 FROM organizations)"
            " OR EXISTS (SELECT 1 FROM opportunities)"
            " OR EXISTS (SELECT 1 FROM activities)"
            " OR EXISTS (SELECT 1 FROM pipeline_stages WHERE product_lane IS NOT NULL)"
        )
    )
    lanes: list[Lane] = list(TATUM_GAMES_LANES if existing_installation else GENERIC_LANES)
    known = {lane[0] for lane in lanes} | {lane[0] for lane in TATUM_GAMES_LANES}
    used = connection.scalars(
        sa.text(
            "SELECT product_lane FROM opportunities WHERE product_lane IS NOT NULL"
            " UNION SELECT product_lane FROM pipeline_stages WHERE product_lane IS NOT NULL"
            " ORDER BY 1"
        )
    ).all()
    presets = {lane[0]: lane for lane in TATUM_GAMES_LANES}
    for key in used:
        if key in presets and presets[key] not in lanes:
            lanes.append(presets[key])
        elif key not in known:
            lanes.append((key, key.replace("_", " ").capitalize(), None, None, False))
            known.add(key)
    return lanes


def upgrade() -> None:
    op.create_table(
        "sales_lanes",
        sa.Column("key", sa.String(length=32), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("color", sa.String(length=16), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("technical_handoff", sa.Boolean(), nullable=False),
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        *_bookkeeping(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sales_lanes")),
    )
    op.create_index("uq_sales_lanes_key", "sales_lanes", ["key"], unique=True)
    op.create_index(
        op.f("ix_sales_lanes_updated_at_utc"), "sales_lanes", ["updated_at_utc"], unique=False
    )

    op.create_table(
        "custom_fields",
        sa.Column("record_type", sa.String(length=16), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("field_type", sa.String(length=16), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(length=27), nullable=True),
        *_bookkeeping(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_custom_fields")),
    )
    op.create_index(
        "uq_custom_fields_record_type_key", "custom_fields", ["record_type", "key"], unique=True
    )
    op.create_index(
        op.f("ix_custom_fields_updated_at_utc"), "custom_fields", ["updated_at_utc"], unique=False
    )

    json_type = sa.JSON().with_variant(postgresql.JSONB(astext_type=sa.Text()), "postgresql")
    op.add_column("organizations", sa.Column("reviewed_on", sa.Date(), nullable=True))
    op.add_column("organizations", sa.Column("qualification_source_url", sa.Text(), nullable=True))
    for table in ("organizations", "contacts"):
        op.add_column(
            table,
            sa.Column(
                "custom_fields", json_type, nullable=False, server_default=sa.text("'{}'::jsonb")
            ),
        )

    connection = op.get_bind()
    lanes = sa.table(
        "sales_lanes",
        sa.column("id", sa.String),
        sa.column("key", sa.String),
        sa.column("name", sa.Text),
        sa.column("description", sa.Text),
        sa.column("color", sa.String),
        sa.column("sort_order", sa.Integer),
        sa.column("technical_handoff", sa.Boolean),
        sa.column("created_at_utc", sa.DateTime(timezone=True)),
        sa.column("updated_at_utc", sa.DateTime(timezone=True)),
        sa.column("created_by_device_id", sa.String),
    )
    op.bulk_insert(
        lanes,
        [
            {
                "id": str(uuid.uuid5(NAMESPACE, f"sales_lane:{key}")),
                "key": key,
                "name": name,
                "description": description,
                "color": color,
                "sort_order": (index + 1) * 10,
                "technical_handoff": handoff,
                "created_at_utc": SEED_TIMESTAMP,
                "updated_at_utc": SEED_TIMESTAMP,
                "created_by_device_id": SYSTEM_DEVICE_ID,
            }
            for index, (key, name, color, description, handoff) in enumerate(
                _lanes_to_seed(connection)
            )
        ],
    )

    for table in NEW_SYNCED_TABLES:
        op.execute(
            f"CREATE TRIGGER trg_{table}_change_log AFTER INSERT OR UPDATE ON {table} "
            "FOR EACH ROW EXECUTE FUNCTION tg_record_change()"
        )


def downgrade() -> None:
    for table in NEW_SYNCED_TABLES:
        op.execute(f"DROP TRIGGER IF EXISTS trg_{table}_change_log ON {table}")
    op.execute("DELETE FROM change_log WHERE entity_table IN ('sales_lanes', 'custom_fields')")
    op.drop_column("contacts", "custom_fields")
    op.drop_column("organizations", "custom_fields")
    op.drop_column("organizations", "qualification_source_url")
    op.drop_column("organizations", "reviewed_on")
    op.drop_index(op.f("ix_custom_fields_updated_at_utc"), table_name="custom_fields")
    op.drop_index("uq_custom_fields_record_type_key", table_name="custom_fields")
    op.drop_table("custom_fields")
    op.drop_index(op.f("ix_sales_lanes_updated_at_utc"), table_name="sales_lanes")
    op.drop_index("uq_sales_lanes_key", table_name="sales_lanes")
    op.drop_table("sales_lanes")
