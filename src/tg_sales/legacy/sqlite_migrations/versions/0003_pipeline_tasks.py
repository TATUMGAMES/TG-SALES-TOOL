# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Opportunity tasks and won/lost reason codes.

Adds the ``tasks`` table and ``opportunities.outcome_reason_code``.

Revision ID: 0003
Revises: 0002
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

import tg_sales.db.types

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("opportunities", schema=None) as batch_op:
        batch_op.add_column(sa.Column("outcome_reason_code", sa.String(length=32), nullable=True))

    op.create_table(
        "tasks",
        sa.Column("opportunity_id", sa.String(length=36), nullable=True),
        sa.Column("organization_id", sa.String(length=36), nullable=True),
        sa.Column("assignee_actor_id", sa.String(length=36), nullable=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("due_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("completed_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["assignee_actor_id"], ["actors.id"], name=op.f("fk_tasks_assignee_actor_id_actors")
        ),
        sa.ForeignKeyConstraint(
            ["opportunity_id"],
            ["opportunities.id"],
            name=op.f("fk_tasks_opportunity_id_opportunities"),
        ),
        sa.ForeignKeyConstraint(
            ["organization_id"],
            ["organizations.id"],
            name=op.f("fk_tasks_organization_id_organizations"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_tasks")),
    )
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_tasks_assignee_actor_id"), ["assignee_actor_id"], unique=False
        )
        batch_op.create_index("ix_tasks_due_at_utc", ["due_at_utc"], unique=False)
        batch_op.create_index(
            batch_op.f("ix_tasks_opportunity_id"), ["opportunity_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_tasks_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_tasks_updated_at_utc"), ["updated_at_utc"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("tasks", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_tasks_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_tasks_organization_id"))
        batch_op.drop_index(batch_op.f("ix_tasks_opportunity_id"))
        batch_op.drop_index("ix_tasks_due_at_utc")
        batch_op.drop_index(batch_op.f("ix_tasks_assignee_actor_id"))
    op.drop_table("tasks")
    with op.batch_alter_table("opportunities", schema=None) as batch_op:
        batch_op.drop_column("outcome_reason_code")
