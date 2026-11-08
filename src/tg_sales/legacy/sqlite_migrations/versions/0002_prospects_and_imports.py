"""Prospect archiving and reversible imports.

Adds ``archived_at_utc`` to organizations and contacts, warning counts and
undo time to import jobs, and the ``import_changes`` table that records what
each import created or updated.

Revision ID: 0002
Revises: 0001
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import tg_sales.db.types

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True)
        )
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("archived_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True)
        )
    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.add_column(
            sa.Column("warning_count", sa.Integer(), nullable=False, server_default=sa.text("0"))
        )
        batch_op.add_column(
            sa.Column("undone_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True)
        )

    op.create_table(
        "import_changes",
        sa.Column("import_job_id", sa.String(length=36), nullable=False),
        sa.Column("entity_table", sa.String(length=64), nullable=False),
        sa.Column("entity_id", sa.String(length=36), nullable=False),
        sa.Column("action", sa.String(length=16), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=True),
        sa.Column("row_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("previous_values", sa.JSON(), nullable=False),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["import_job_id"],
            ["import_jobs.id"],
            name=op.f("fk_import_changes_import_job_id_import_jobs"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_import_changes")),
    )
    with op.batch_alter_table("import_changes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_import_changes_entity_id"), ["entity_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_import_changes_import_job_id"), ["import_job_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_import_changes_row_fingerprint"), ["row_fingerprint"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_import_changes_updated_at_utc"), ["updated_at_utc"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("import_changes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_import_changes_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_import_changes_row_fingerprint"))
        batch_op.drop_index(batch_op.f("ix_import_changes_import_job_id"))
        batch_op.drop_index(batch_op.f("ix_import_changes_entity_id"))
    op.drop_table("import_changes")
    with op.batch_alter_table("import_jobs", schema=None) as batch_op:
        batch_op.drop_column("undone_at_utc")
        batch_op.drop_column("warning_count")
    with op.batch_alter_table("contacts", schema=None) as batch_op:
        batch_op.drop_column("archived_at_utc")
    with op.batch_alter_table("organizations", schema=None) as batch_op:
        batch_op.drop_column("archived_at_utc")
