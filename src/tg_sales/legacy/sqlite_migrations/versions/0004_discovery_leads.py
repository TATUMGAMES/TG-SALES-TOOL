"""Discovery review queue.

Adds the ``discovery_leads`` table.

Revision ID: 0004
Revises: 0003
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import tg_sales.db.types

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discovery_leads",
        sa.Column("run_id", sa.String(length=36), nullable=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("external_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
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
        sa.Column("last_checked_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_discovery_leads_organization_id_organizations"),
        ),
        sa.ForeignKeyConstraint(
            ["run_id"], ["discovery_runs.id"], name=op.f("fk_discovery_leads_run_id_discovery_runs")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discovery_leads")),
    )
    with op.batch_alter_table("discovery_leads", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_discovery_leads_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(batch_op.f("ix_discovery_leads_run_id"), ["run_id"], unique=False)
        batch_op.create_index("ix_discovery_leads_status", ["status"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_discovery_leads_updated_at_utc"), ["updated_at_utc"], unique=False
        )
        batch_op.create_index(
            "uq_discovery_leads_source_external_id",
            ["source", "external_id"],
            unique=True,
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
        )


def downgrade() -> None:
    with op.batch_alter_table("discovery_leads", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_discovery_leads_source_external_id",
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
        )
        batch_op.drop_index(batch_op.f("ix_discovery_leads_updated_at_utc"))
        batch_op.drop_index("ix_discovery_leads_status")
        batch_op.drop_index(batch_op.f("ix_discovery_leads_run_id"))
        batch_op.drop_index(batch_op.f("ix_discovery_leads_organization_id"))
    op.drop_table("discovery_leads")
