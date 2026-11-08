"""Enumerated values stored in the database.

Values are stored as their lowercase text form so the database stays readable
and sync packages remain stable across application versions. Unknown is an
explicit value wherever information may be missing, so that "not known" is
never confused with "no".
"""

from __future__ import annotations

from enum import StrEnum


class ProductLane(StrEnum):
    DATA_LICENSING = "data_licensing"
    PUBLISHER_PARTNERSHIP = "publisher_partnership"
    MIKROS_MARKETING = "mikros_marketing"


class OrganizationType(StrEnum):
    UNKNOWN = "unknown"
    STUDIO = "studio"
    PUBLISHER = "publisher"
    DATA_BUYER = "data_buyer"
    OTHER = "other"


class ContactStatus(StrEnum):
    """Outreach state of a contact; UNKNOWN preserves missing information."""

    UNKNOWN = "unknown"
    NOT_CONTACTED = "not_contacted"
    ATTEMPTED = "attempted"
    RESPONDED = "responded"


class ReleasePrecision(StrEnum):
    """How precisely a game's release date is known ("Coming soon" is UNKNOWN)."""

    DAY = "day"
    MONTH = "month"
    QUARTER = "quarter"
    YEAR = "year"
    UNKNOWN = "unknown"


class GameRole(StrEnum):
    """An organization's role for a game. A game can have several of each."""

    DEVELOPER = "developer"
    PUBLISHER = "publisher"


class StageOutcome(StrEnum):
    """What reaching a pipeline stage means; any value except OPEN is terminal."""

    OPEN = "open"
    WON = "won"
    LOST = "lost"
    NOT_A_FIT = "not_a_fit"

    @property
    def is_terminal(self) -> bool:
        return self is not StageOutcome.OPEN


class RecordSource(StrEnum):
    """Where a record or event came from."""

    MANUAL = "manual"
    IMPORT = "import"
    DISCOVERY = "discovery"
    SYNC = "sync"
    SYSTEM = "system"


class SettingScope(StrEnum):
    """SHARED settings travel with sync packages; DEVICE settings never leave this computer."""

    SHARED = "shared"
    DEVICE = "device"


class ActivityType(StrEnum):
    """Kinds of immutable activity events."""

    # Lifecycle and pipeline events written by the application.
    OPPORTUNITY_CREATED = "opportunity_created"
    STAGE_CHANGE = "stage_change"
    FIELD_CHANGE = "field_change"
    CORRECTION = "correction"
    NOTE = "note"
    ORGANIZATION_CREATED = "organization_created"
    IMPORT_COMMITTED = "import_committed"
    IMPORT_UNDONE = "import_undone"
    TASK_CREATED = "task_created"
    TASK_COMPLETED = "task_completed"
    # Outreach and interactions logged by salespeople.
    CONTACTED = "contacted"
    EMAIL = "email"
    LINKEDIN_INVITE = "linkedin_invite"
    LINKEDIN_MESSAGE = "linkedin_message"
    PHONE_CALL = "phone_call"
    MEETING = "meeting"
    REPLY = "reply"
    DEMO = "demo"
    DATA_ROOM_SHARED = "data_room_shared"
    TECHNICAL_HANDOFF = "technical_handoff"
    PROPOSAL = "proposal"
    WON = "won"
    LOST = "lost"
    CLOSED = "closed"


# Attempts to reach a contact that we initiated (used by "contacted" metrics).
OUTREACH_ACTIVITY_TYPES = frozenset(
    {
        ActivityType.CONTACTED,
        ActivityType.EMAIL,
        ActivityType.LINKEDIN_INVITE,
        ActivityType.LINKEDIN_MESSAGE,
        ActivityType.PHONE_CALL,
    }
)

# Events that place an opportunity in a stage (used for historical snapshots).
STAGE_ACTIVITY_TYPES = frozenset({ActivityType.OPPORTUNITY_CREATED, ActivityType.STAGE_CHANGE})
