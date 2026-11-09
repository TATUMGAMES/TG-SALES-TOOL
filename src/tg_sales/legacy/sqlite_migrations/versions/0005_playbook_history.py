# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Playbook revision history and outcome notes.

Adds ``playbook_revisions`` and ``playbook_outcomes``, and
``playbook_templates.example_key`` (identifies the built-in example templates
so adding them twice is avoided).

Revision ID: 0005
Revises: 0004
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa
from alembic import op

import tg_sales.db.types

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EXAMPLE_KEY_WHERE = sa.text("deleted_at_utc IS NULL AND example_key IS NOT NULL")


def _bookkeeping() -> list[sa.Column[Any]]:
    return [
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("created_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("updated_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("created_by_device_id", sa.String(length=36), nullable=False),
        sa.Column("deleted_at_utc", tg_sales.db.types.UTCDateTime(), nullable=True),
    ]


def upgrade() -> None:
    with op.batch_alter_table("playbook_templates", schema=None) as batch_op:
        batch_op.add_column(sa.Column("example_key", sa.String(length=64), nullable=True))
        batch_op.create_index(
            "uq_playbook_templates_example_key",
            ["example_key"],
            unique=True,
            sqlite_where=EXAMPLE_KEY_WHERE,
        )

    op.create_table(
        "playbook_revisions",
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content", sa.JSON(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("author_actor_id", sa.String(length=36), nullable=True),
        *_bookkeeping(),
        sa.ForeignKeyConstraint(
            ["author_actor_id"],
            ["actors.id"],
            name=op.f("fk_playbook_revisions_author_actor_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["playbook_templates.id"],
            name=op.f("fk_playbook_revisions_template_id_playbook_templates"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_revisions")),
    )
    with op.batch_alter_table("playbook_revisions", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_playbook_revisions_author_actor_id"), ["author_actor_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_playbook_revisions_template_id"), ["template_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_playbook_revisions_updated_at_utc"), ["updated_at_utc"], unique=False
        )
        batch_op.create_index(
            "uq_playbook_revisions_template_id_revision",
            ["template_id", "revision"],
            unique=True,
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
        )

    op.create_table(
        "playbook_outcomes",
        sa.Column("template_id", sa.String(length=36), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(length=24), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("recorded_at_utc", tg_sales.db.types.UTCDateTime(), nullable=False),
        sa.Column("author_actor_id", sa.String(length=36), nullable=True),
        *_bookkeeping(),
        sa.ForeignKeyConstraint(
            ["author_actor_id"],
            ["actors.id"],
            name=op.f("fk_playbook_outcomes_author_actor_id_actors"),
        ),
        sa.ForeignKeyConstraint(
            ["template_id"],
            ["playbook_templates.id"],
            name=op.f("fk_playbook_outcomes_template_id_playbook_templates"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_playbook_outcomes")),
    )
    with op.batch_alter_table("playbook_outcomes", schema=None) as batch_op:
        batch_op.create_index(
            batch_op.f("ix_playbook_outcomes_author_actor_id"), ["author_actor_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_playbook_outcomes_template_id"), ["template_id"], unique=False
        )
        batch_op.create_index(
            batch_op.f("ix_playbook_outcomes_updated_at_utc"), ["updated_at_utc"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("playbook_outcomes", schema=None) as batch_op:
        batch_op.drop_index(batch_op.f("ix_playbook_outcomes_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_playbook_outcomes_template_id"))
        batch_op.drop_index(batch_op.f("ix_playbook_outcomes_author_actor_id"))
    op.drop_table("playbook_outcomes")
    with op.batch_alter_table("playbook_revisions", schema=None) as batch_op:
        batch_op.drop_index(
            "uq_playbook_revisions_template_id_revision",
            sqlite_where=sa.text("deleted_at_utc IS NULL"),
        )
        batch_op.drop_index(batch_op.f("ix_playbook_revisions_updated_at_utc"))
        batch_op.drop_index(batch_op.f("ix_playbook_revisions_template_id"))
        batch_op.drop_index(batch_op.f("ix_playbook_revisions_author_actor_id"))
    op.drop_table("playbook_revisions")
    with op.batch_alter_table("playbook_templates", schema=None) as batch_op:
        batch_op.drop_index("uq_playbook_templates_example_key", sqlite_where=EXAMPLE_KEY_WHERE)
        batch_op.drop_column("example_key")
