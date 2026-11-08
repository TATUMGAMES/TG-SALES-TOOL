"""SQLAlchemy models for the tg_sales database.

Every table carries the same bookkeeping columns (see :class:`EntityMixin`):
a globally unique ``id``, UTC ``created_at_utc`` / ``updated_at_utc``, the
``created_by_device_id`` of the computer that created the row, and an optional
``deleted_at_utc`` tombstone. Rows are soft-deleted so deletions can be
synchronized between computers.

PostgreSQL is the primary database: its schema is created and upgraded only
by the Alembic migrations in ``tg_sales/db/migrations_pg``. Databases from the
earlier desktop version (SQLite, ``tg_sales/db/migrations``) are only read by
the legacy transfer tool. Tests verify that both migration chains match these
models. See docs/DATA_MODEL.md for the documented schema.
"""

from __future__ import annotations

import enum
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    Date,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.schema import Identity

from tg_sales.db.types import UTCDateTime, json_type
from tg_sales.domain.enums import (
    ActivityType,
    ContactStatus,
    GameRole,
    OrganizationType,
    ProductLane,
    RecordSource,
    ReleasePrecision,
    SettingScope,
    StageOutcome,
)

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

ID_LENGTH = 36
NOT_DELETED = text("deleted_at_utc IS NULL")


def partial(condition: str = "deleted_at_utc IS NULL") -> dict[str, Any]:
    """Dialect options for a partial index limited to ``condition``."""
    clause = text(condition)
    return {"sqlite_where": clause, "postgresql_where": clause}


def enum_column[E: enum.Enum](enum_cls: type[E]) -> Enum:
    """Store an enum as its text value; validated in Python, no database CHECK.

    Avoiding CHECK constraints lets future versions add values without
    rebuilding tables.
    """
    return Enum(
        enum_cls,
        native_enum=False,
        create_constraint=False,
        length=32,
        validate_strings=True,
        values_callable=lambda members: [member.value for member in members],
    )


def id_column(*, primary_key: bool = False) -> Mapped[str]:
    return mapped_column(String(ID_LENGTH), primary_key=primary_key)


def fk_column(target: str, *, nullable: bool, index: bool = True) -> Mapped[Any]:
    # Deferrable (checked at statement end unless a transaction defers them) so
    # that bulk imports and sync merges can insert related rows in any order.
    return mapped_column(
        String(ID_LENGTH),
        ForeignKey(target, deferrable=True, initially="IMMEDIATE"),
        nullable=nullable,
        index=index,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {  # noqa: RUF012 - SQLAlchemy configuration mapping
        datetime: UTCDateTime(),
        dict[str, Any]: json_type(),
        list[str]: json_type(),
        str: Text(),
    }


class EntityMixin:
    """Bookkeeping columns shared by every table."""

    id: Mapped[str] = id_column(primary_key=True)
    created_at_utc: Mapped[datetime]
    updated_at_utc: Mapped[datetime] = mapped_column(index=True)
    created_by_device_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    deleted_at_utc: Mapped[datetime | None]

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at_utc is not None


class Actor(EntityMixin, Base):
    """A person who owns opportunities and performs activities."""

    __tablename__ = "actors"

    display_name: Mapped[str]


class Organization(EntityMixin, Base):
    __tablename__ = "organizations"
    __table_args__ = (Index("ix_organizations_created_at_utc", "created_at_utc"),)

    name: Mapped[str]
    normalized_name: Mapped[str] = mapped_column(index=True)
    website: Mapped[str | None]
    domain: Mapped[str | None] = mapped_column(index=True)
    location: Mapped[str | None]
    country: Mapped[str | None]
    company_type: Mapped[OrganizationType] = mapped_column(
        enum_column(OrganizationType), default=OrganizationType.UNKNOWN
    )
    source: Mapped[RecordSource] = mapped_column(
        enum_column(RecordSource), default=RecordSource.MANUAL
    )
    tags: Mapped[list[str]] = mapped_column(default=list)
    notes: Mapped[str | None]
    archived_at_utc: Mapped[datetime | None]


class Contact(EntityMixin, Base):
    __tablename__ = "contacts"
    __table_args__ = (Index("ix_contacts_created_at_utc", "created_at_utc"),)

    organization_id: Mapped[str] = fk_column("organizations.id", nullable=False)
    name: Mapped[str | None]
    role_title: Mapped[str | None]
    business_email: Mapped[str | None]
    email_normalized: Mapped[str | None] = mapped_column(index=True)
    social_urls: Mapped[dict[str, Any]] = mapped_column(default=dict)
    contact_status: Mapped[ContactStatus] = mapped_column(
        enum_column(ContactStatus), default=ContactStatus.UNKNOWN
    )
    notes: Mapped[str | None]
    provenance: Mapped[str | None]
    source_url: Mapped[str | None]
    source: Mapped[RecordSource] = mapped_column(
        enum_column(RecordSource), default=RecordSource.MANUAL
    )
    archived_at_utc: Mapped[datetime | None]


class Game(EntityMixin, Base):
    __tablename__ = "games"
    __table_args__ = (
        Index(
            "uq_games_store_store_id",
            "store",
            "store_id",
            unique=True,
            **partial("deleted_at_utc IS NULL AND store_id IS NOT NULL"),
        ),
        Index("ix_games_release_date", "release_date"),
    )

    title: Mapped[str]
    platform: Mapped[str | None]
    store: Mapped[str | None]
    store_id: Mapped[str | None]
    store_url: Mapped[str | None]
    release_date: Mapped[date | None] = mapped_column(Date())
    release_precision: Mapped[ReleasePrecision] = mapped_column(
        enum_column(ReleasePrecision), default=ReleasePrecision.UNKNOWN
    )
    source: Mapped[RecordSource] = mapped_column(
        enum_column(RecordSource), default=RecordSource.MANUAL
    )
    discovered_at_utc: Mapped[datetime | None]


class GameOrganization(EntityMixin, Base):
    """Links a game to its developers and publishers (many-to-many with role)."""

    __tablename__ = "game_organizations"
    __table_args__ = (
        Index(
            "uq_game_organizations_game_id_organization_id_role",
            "game_id",
            "organization_id",
            "role",
            unique=True,
            **partial(),
        ),
    )

    game_id: Mapped[str] = fk_column("games.id", nullable=False)
    organization_id: Mapped[str] = fk_column("organizations.id", nullable=False)
    role: Mapped[GameRole] = mapped_column(enum_column(GameRole))


class PipelineStage(EntityMixin, Base):
    __tablename__ = "pipeline_stages"

    name: Mapped[str]
    sort_order: Mapped[int] = mapped_column(Integer())
    product_lane: Mapped[ProductLane | None] = mapped_column(enum_column(ProductLane))
    outcome: Mapped[StageOutcome] = mapped_column(
        enum_column(StageOutcome), default=StageOutcome.OPEN
    )
    archived_at_utc: Mapped[datetime | None]

    @property
    def is_terminal(self) -> bool:
        return self.outcome.is_terminal


class Opportunity(EntityMixin, Base):
    __tablename__ = "opportunities"
    __table_args__ = (
        CheckConstraint(
            "probability IS NULL OR (probability >= 0 AND probability <= 1)",
            name="probability_range",
        ),
        CheckConstraint(
            "estimated_value IS NULL OR estimated_value >= 0", name="estimated_value_positive"
        ),
        Index("ix_opportunities_next_action_at_utc", "next_action_at_utc"),
        Index("ix_opportunities_product_lane", "product_lane"),
    )

    organization_id: Mapped[str] = fk_column("organizations.id", nullable=False)
    product_lane: Mapped[ProductLane] = mapped_column(enum_column(ProductLane))
    stage_id: Mapped[str] = fk_column("pipeline_stages.id", nullable=False)
    owner_actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)
    title: Mapped[str | None]
    estimated_value: Mapped[float | None] = mapped_column(Float())
    currency: Mapped[str | None] = mapped_column(String(3))
    probability: Mapped[float | None] = mapped_column(Float())
    next_action_at_utc: Mapped[datetime | None]
    next_action_note: Mapped[str | None]
    outcome_reason: Mapped[str | None]
    outcome_reason_code: Mapped[str | None] = mapped_column(String(32))
    closed_at_utc: Mapped[datetime | None]


class Task(EntityMixin, Base):
    """A to-do item, usually for an opportunity (for example "Send sample data")."""

    __tablename__ = "tasks"
    __table_args__ = (Index("ix_tasks_due_at_utc", "due_at_utc"),)

    opportunity_id: Mapped[str | None] = fk_column("opportunities.id", nullable=True)
    organization_id: Mapped[str | None] = fk_column("organizations.id", nullable=True)
    assignee_actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)
    title: Mapped[str]
    due_at_utc: Mapped[datetime | None]
    completed_at_utc: Mapped[datetime | None]


class Activity(EntityMixin, Base):
    """Immutable event. ``id`` is the event id; ``created_at_utc`` is when it was recorded.

    Rows can never be updated or deleted (enforced by database triggers);
    mistakes are fixed by recording a ``correction`` event that references the
    original through ``corrects_event_id``.
    """

    __tablename__ = "activities"
    __table_args__ = (
        Index("ix_activities_occurred_at_utc", "occurred_at_utc"),
        Index("ix_activities_type_occurred_at_utc", "type", "occurred_at_utc"),
        Index("ix_activities_opportunity_id_occurred_at_utc", "opportunity_id", "occurred_at_utc"),
    )

    occurred_at_utc: Mapped[datetime]
    type: Mapped[ActivityType] = mapped_column(enum_column(ActivityType))
    actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)
    organization_id: Mapped[str | None] = fk_column("organizations.id", nullable=True)
    contact_id: Mapped[str | None] = fk_column("contacts.id", nullable=True)
    opportunity_id: Mapped[str | None] = fk_column("opportunities.id", nullable=True, index=False)
    game_id: Mapped[str | None] = fk_column("games.id", nullable=True)
    corrects_event_id: Mapped[str | None] = fk_column("activities.id", nullable=True)
    payload: Mapped[dict[str, Any]] = mapped_column(default=dict)
    source: Mapped[RecordSource] = mapped_column(
        enum_column(RecordSource), default=RecordSource.MANUAL
    )


class PlaybookTemplate(EntityMixin, Base):
    """An outreach message template. Every saved edit adds a ``PlaybookRevision``."""

    __tablename__ = "playbook_templates"
    __table_args__ = (
        Index(
            "uq_playbook_templates_example_key",
            "example_key",
            unique=True,
            **partial("deleted_at_utc IS NULL AND example_key IS NOT NULL"),
        ),
    )

    title: Mapped[str]
    label: Mapped[str | None]
    category: Mapped[str | None]
    channel: Mapped[str | None]
    audience: Mapped[str | None]
    stage: Mapped[str | None]
    body: Mapped[str]
    notes: Mapped[str | None]
    author_actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)
    tags: Mapped[list[str]] = mapped_column(default=list)
    is_favorite: Mapped[bool] = mapped_column(Boolean(), default=False)
    is_approved: Mapped[bool] = mapped_column(Boolean(), default=False)
    revision: Mapped[int] = mapped_column(Integer(), default=1)
    archived_at_utc: Mapped[datetime | None]
    example_key: Mapped[str | None] = mapped_column(String(64))


class PlaybookRevision(EntityMixin, Base):
    """The full content of a template as saved at one revision."""

    __tablename__ = "playbook_revisions"
    __table_args__ = (
        Index(
            "uq_playbook_revisions_template_id_revision",
            "template_id",
            "revision",
            unique=True,
            **partial(),
        ),
    )

    template_id: Mapped[str] = fk_column("playbook_templates.id", nullable=False)
    revision: Mapped[int] = mapped_column(Integer())
    content: Mapped[dict[str, Any]] = mapped_column(default=dict)
    summary: Mapped[str]
    author_actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)


class PlaybookOutcome(EntityMixin, Base):
    """A manually recorded result of using a template."""

    __tablename__ = "playbook_outcomes"

    template_id: Mapped[str] = fk_column("playbook_templates.id", nullable=False)
    revision: Mapped[int] = mapped_column(Integer())
    outcome: Mapped[str] = mapped_column(String(24))
    note: Mapped[str | None]
    recorded_at_utc: Mapped[datetime]
    author_actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)


class ImportJob(EntityMixin, Base):
    __tablename__ = "import_jobs"

    file_name: Mapped[str]
    file_sha256: Mapped[str] = mapped_column(String(64), index=True)
    file_size_bytes: Mapped[int] = mapped_column(Integer())
    file_type: Mapped[str] = mapped_column(String(16))
    sheet_name: Mapped[str | None]
    status: Mapped[str] = mapped_column(String(32))
    started_at_utc: Mapped[datetime]
    finished_at_utc: Mapped[datetime | None]
    created_count: Mapped[int] = mapped_column(Integer(), default=0)
    updated_count: Mapped[int] = mapped_column(Integer(), default=0)
    skipped_count: Mapped[int] = mapped_column(Integer(), default=0)
    error_count: Mapped[int] = mapped_column(Integer(), default=0)
    warning_count: Mapped[int] = mapped_column(Integer(), default=0)
    mapping: Mapped[dict[str, Any]] = mapped_column(default=dict)
    error_summary: Mapped[str | None]
    undone_at_utc: Mapped[datetime | None]


class ImportChange(EntityMixin, Base):
    """One record created or updated by an import, so the import can be undone.

    ``previous_values`` holds the values an update replaced (empty for
    created records). ``row_fingerprint`` identifies the source row content so
    re-importing the same rows is recognized.
    """

    __tablename__ = "import_changes"

    import_job_id: Mapped[str] = fk_column("import_jobs.id", nullable=False)
    entity_table: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(ID_LENGTH), index=True)
    action: Mapped[str] = mapped_column(String(16))
    row_number: Mapped[int | None] = mapped_column(Integer())
    row_fingerprint: Mapped[str | None] = mapped_column(String(64), index=True)
    previous_values: Mapped[dict[str, Any]] = mapped_column(default=dict)


class DiscoveryRun(EntityMixin, Base):
    __tablename__ = "discovery_runs"

    source: Mapped[str] = mapped_column(String(64))
    parameters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(32))
    started_at_utc: Mapped[datetime]
    finished_at_utc: Mapped[datetime | None]
    result_count: Mapped[int] = mapped_column(Integer(), default=0)
    error: Mapped[str | None]


class DiscoveryLead(EntityMixin, Base):
    """A game found by discovery, waiting for review (the human review queue).

    One row per source game (``source`` + ``external_id``); later runs refresh
    the data but keep the review status and any verified contact.
    """

    __tablename__ = "discovery_leads"
    __table_args__ = (
        Index(
            "uq_discovery_leads_source_external_id",
            "source",
            "external_id",
            unique=True,
            **partial(),
        ),
        Index("ix_discovery_leads_status", "status"),
    )

    run_id: Mapped[str | None] = fk_column("discovery_runs.id", nullable=True)
    source: Mapped[str] = mapped_column(String(32))
    external_id: Mapped[str] = mapped_column(String(64))
    title: Mapped[str]
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    release_date: Mapped[date | None] = mapped_column(Date())
    release_precision: Mapped[ReleasePrecision] = mapped_column(
        enum_column(ReleasePrecision), default=ReleasePrecision.UNKNOWN
    )
    status: Mapped[str] = mapped_column(String(16))
    contact_status: Mapped[str] = mapped_column(String(24))
    contact_email: Mapped[str | None]
    contact_source_url: Mapped[str | None]
    provenance_url: Mapped[str]
    last_checked_at_utc: Mapped[datetime]
    organization_id: Mapped[str | None] = fk_column("organizations.id", nullable=True)


class SyncExport(EntityMixin, Base):
    """A change package exported from this computer; ``id`` is the export id."""

    __tablename__ = "sync_exports"

    file_name: Mapped[str]
    watermark: Mapped[dict[str, Any]] = mapped_column(default=dict)
    record_count: Mapped[int] = mapped_column(Integer(), default=0)
    event_count: Mapped[int] = mapped_column(Integer(), default=0)
    encrypted: Mapped[bool] = mapped_column(Boolean(), default=False)


class SyncImport(EntityMixin, Base):
    __tablename__ = "sync_imports"
    __table_args__ = (Index("uq_sync_imports_export_id", "export_id", unique=True, **partial()),)

    export_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    source_device_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    file_name: Mapped[str]
    file_sha256: Mapped[str] = mapped_column(String(64))
    status: Mapped[str] = mapped_column(String(32))
    imported_at_utc: Mapped[datetime | None]
    counts: Mapped[dict[str, Any]] = mapped_column(default=dict)


class Conflict(EntityMixin, Base):
    __tablename__ = "conflicts"
    __table_args__ = (Index("ix_conflicts_entity_table_entity_id", "entity_table", "entity_id"),)

    sync_import_id: Mapped[str | None] = fk_column("sync_imports.id", nullable=True)
    entity_table: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    field: Mapped[str | None] = mapped_column(String(64))
    local_value: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    incoming_value: Mapped[dict[str, Any] | None] = mapped_column(json_type())
    status: Mapped[str] = mapped_column(String(32))
    resolution: Mapped[str | None] = mapped_column(String(32))
    resolved_at_utc: Mapped[datetime | None]
    resolved_by_actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)


class SyncPending(EntityMixin, Base):
    """A received record waiting for a record it refers to (packages imported out of order).

    Retried after every sync import; applied as soon as its references exist.
    """

    __tablename__ = "sync_pending"
    __table_args__ = (
        Index(
            "uq_sync_pending_entity_table_entity_id_change_id",
            "entity_table",
            "entity_id",
            "change_id",
            unique=True,
        ),
    )

    sync_import_id: Mapped[str | None] = fk_column("sync_imports.id", nullable=True)
    entity_table: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    change_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    record: Mapped[dict[str, Any]] = mapped_column(default=dict)
    reason: Mapped[str]


class Attachment(EntityMixin, Base):
    __tablename__ = "attachments"

    organization_id: Mapped[str | None] = fk_column("organizations.id", nullable=True)
    contact_id: Mapped[str | None] = fk_column("contacts.id", nullable=True)
    opportunity_id: Mapped[str | None] = fk_column("opportunities.id", nullable=True)
    file_name: Mapped[str]
    relative_path: Mapped[str]
    sha256: Mapped[str] = mapped_column(String(64))
    size_bytes: Mapped[int] = mapped_column(Integer())
    media_type: Mapped[str | None] = mapped_column(String(128))


class Snapshot(EntityMixin, Base):
    """A saved dashboard snapshot image."""

    __tablename__ = "snapshots"

    relative_path: Mapped[str]
    filters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    generated_at_utc: Mapped[datetime]
    app_version: Mapped[str] = mapped_column(String(32))
    width_px: Mapped[int | None] = mapped_column(Integer())
    height_px: Mapped[int | None] = mapped_column(Integer())


class Setting(EntityMixin, Base):
    """Key/value setting. DEVICE-scoped settings are never synced."""

    __tablename__ = "settings"
    __table_args__ = (Index("uq_settings_key_scope", "key", "scope", unique=True, **partial()),)

    key: Mapped[str] = mapped_column(String(128))
    scope: Mapped[SettingScope] = mapped_column(enum_column(SettingScope))
    value: Mapped[Any] = mapped_column(json_type())


class ReportRecord(EntityMixin, Base):
    """Metadata of a generated report; the files live in the reports data folder."""

    __tablename__ = "report_records"
    __table_args__ = (Index("uq_report_records_folder_name", "folder_name", unique=True),)

    folder_name: Mapped[str] = mapped_column(String(128))
    title: Mapped[str]
    period_start: Mapped[date] = mapped_column(Date())
    period_end: Mapped[date] = mapped_column(Date())
    filters: Mapped[dict[str, Any]] = mapped_column(default=dict)
    generated_at_utc: Mapped[datetime]
    app_version: Mapped[str] = mapped_column(String(32))
    page_count: Mapped[int | None] = mapped_column(Integer())
    has_html: Mapped[bool] = mapped_column(Boolean(), default=False)
    totals: Mapped[dict[str, Any]] = mapped_column(default=dict)
    author_actor_id: Mapped[str | None] = fk_column("actors.id", nullable=True)


class ResourceLink(EntityMixin, Base):
    """A bookmark on the Resources page.

    ``kind`` is ``link`` (an http(s) URL, shared through sync) or ``folder``
    (a folder on this computer, never synced because paths differ per computer).
    """

    __tablename__ = "resource_links"

    title: Mapped[str]
    kind: Mapped[str] = mapped_column(String(16))
    target: Mapped[str]
    category: Mapped[str | None]
    notes: Mapped[str | None]
    sort_order: Mapped[int] = mapped_column(Integer(), default=0)


class ChangeLog(Base):
    """One row per change to a synchronized record (written by database triggers).

    ``change_id`` identifies the version a change produced. Changes made on this
    computer get a new id; changes applied from a sync package keep the id they
    were given on the computer that made them, which is how repeated, out-of-order
    and onward-forwarded packages are recognized.
    """

    __tablename__ = "change_log"
    __table_args__ = (
        Index("ix_change_log_entity_table_entity_id_seq", "entity_table", "entity_id", "seq"),
        Index(
            "uq_change_log_entity_table_entity_id_change_id",
            "entity_table",
            "entity_id",
            "change_id",
            unique=True,
        ),
    )

    seq: Mapped[int] = mapped_column(BigInteger(), Identity(always=False), primary_key=True)
    entity_table: Mapped[str] = mapped_column(String(64))
    entity_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    change_id: Mapped[str] = mapped_column(String(ID_LENGTH))
    device_id: Mapped[str | None] = mapped_column(String(ID_LENGTH))
    origin: Mapped[str] = mapped_column(String(8))
    changed_at_utc: Mapped[datetime]


# Tables whose rows travel in sync packages (see services/sync.py). Settings
# travel only when SHARED; resource links only when they are web links.
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


ENTITY_MODELS: tuple[type[EntityMixin], ...] = (
    Actor,
    Organization,
    Contact,
    Game,
    GameOrganization,
    PipelineStage,
    Opportunity,
    Task,
    Activity,
    PlaybookTemplate,
    PlaybookRevision,
    PlaybookOutcome,
    ImportJob,
    ImportChange,
    DiscoveryRun,
    DiscoveryLead,
    SyncExport,
    SyncImport,
    SyncPending,
    Conflict,
    Attachment,
    Snapshot,
    Setting,
    ReportRecord,
    ResourceLink,
)
