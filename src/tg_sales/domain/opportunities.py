"""Opportunities, stages and logged interactions: data passed to the UI and rules.

Logged interactions record what a salesperson reports having done. tg_sales
never sends messages itself, so an "email" activity means "an email was logged",
not "tg_sales sent an email".
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from tg_sales.domain.enums import ActivityType, ContactStatus, ProductLane, StageOutcome

MAX_STAGE_NAME_LENGTH = 60

# Interactions a salesperson can log, in menu order, with their labels.
LOGGABLE_ACTIVITIES: tuple[tuple[ActivityType, str], ...] = (
    (ActivityType.EMAIL, "Email"),
    (ActivityType.LINKEDIN_INVITE, "LinkedIn invite"),
    (ActivityType.LINKEDIN_MESSAGE, "LinkedIn message"),
    (ActivityType.PHONE_CALL, "Phone call"),
    (ActivityType.MEETING, "Meeting"),
    (ActivityType.REPLY, "Reply received"),
    (ActivityType.DEMO, "Demo"),
    (ActivityType.DATA_ROOM_SHARED, "Data room shared"),
    (ActivityType.TECHNICAL_HANDOFF, "Technical handoff"),
    (ActivityType.PROPOSAL, "Proposal"),
    (ActivityType.CONTACTED, "Other contact"),
    (ActivityType.CLOSED, "Closed"),
)
LOGGABLE_TYPES = frozenset(t for t, _ in LOGGABLE_ACTIVITIES)

ACTIVITY_LABELS: dict[ActivityType, str] = {
    **dict(LOGGABLE_ACTIVITIES),
    ActivityType.OPPORTUNITY_CREATED: "Opportunity created",
    ActivityType.STAGE_CHANGE: "Stage change",
    ActivityType.FIELD_CHANGE: "Details changed",
    ActivityType.CORRECTION: "Correction",
    ActivityType.NOTE: "Note",
    ActivityType.ORGANIZATION_CREATED: "Prospect created",
    ActivityType.IMPORT_COMMITTED: "Import",
    ActivityType.IMPORT_UNDONE: "Import undone",
    ActivityType.TASK_CREATED: "Task added",
    ActivityType.TASK_COMPLETED: "Task completed",
    ActivityType.WON: "Won",
    ActivityType.LOST: "Lost",
}

# Effect of logging an interaction with a contact on the contact's outreach status.
_ATTEMPT_TYPES = frozenset(
    {
        ActivityType.EMAIL,
        ActivityType.LINKEDIN_INVITE,
        ActivityType.LINKEDIN_MESSAGE,
        ActivityType.PHONE_CALL,
        ActivityType.CONTACTED,
        ActivityType.PROPOSAL,
        ActivityType.DATA_ROOM_SHARED,
    }
)
_RESPONSE_TYPES = frozenset({ActivityType.REPLY, ActivityType.MEETING, ActivityType.DEMO})


def contact_status_after(current: ContactStatus, activity: ActivityType) -> ContactStatus:
    """Outreach status of a contact after an interaction is logged with them.

    Status only moves forward (unknown/not contacted → attempted → responded).
    """
    if activity in _RESPONSE_TYPES:
        return ContactStatus.RESPONDED
    if activity in _ATTEMPT_TYPES and current in (
        ContactStatus.UNKNOWN,
        ContactStatus.NOT_CONTACTED,
    ):
        return ContactStatus.ATTEMPTED
    return current


# Reason codes required when an opportunity reaches a terminal stage.
REASON_CODES: dict[StageOutcome, tuple[tuple[str, str], ...]] = {
    StageOutcome.WON: (
        ("signed", "Contract signed"),
        ("pilot", "Paid pilot agreed"),
        ("expanded", "Existing customer expanded"),
        ("other", "Other"),
    ),
    StageOutcome.LOST: (
        ("price", "Price or budget"),
        ("timing", "Timing / not now"),
        ("competitor", "Chose a competitor"),
        ("no_response", "No response"),
        ("internal", "Internal decision or priorities"),
        ("data_not_available", "Data not available or not approved"),
        ("other", "Other"),
    ),
    StageOutcome.NOT_A_FIT: (
        ("wrong_segment", "Wrong segment or platform"),
        ("too_small", "Too small"),
        ("no_need", "No need for the product"),
        ("duplicate", "Duplicate opportunity"),
        ("other", "Other"),
    ),
}


def reason_label(outcome: StageOutcome, code: str | None) -> str | None:
    if code is None:
        return None
    return dict(REASON_CODES.get(outcome, ())).get(code, code)


@dataclass(frozen=True)
class StageInfo:
    id: str
    name: str
    sort_order: int
    product_lane: ProductLane | None
    outcome: StageOutcome
    archived: bool
    opportunity_count: int = 0

    @property
    def is_terminal(self) -> bool:
        return self.outcome.is_terminal

    def applies_to(self, lane: ProductLane | None) -> bool:
        return lane is None or self.product_lane is None or self.product_lane is lane


@dataclass(frozen=True)
class OpportunityCard:
    id: str
    organization_id: str
    organization_name: str
    title: str | None
    product_lane: ProductLane
    stage_id: str
    owner_name: str | None
    last_activity_at: datetime | None
    next_action_at: datetime | None
    next_action_note: str | None
    release_date: date | None
    closed: bool

    def overdue(self, now: datetime) -> bool:
        return not self.closed and self.next_action_at is not None and self.next_action_at < now


@dataclass(frozen=True)
class Board:
    stages: tuple[StageInfo, ...]
    cards: tuple[OpportunityCard, ...]

    def cards_in(self, stage_id: str) -> list[OpportunityCard]:
        return [c for c in self.cards if c.stage_id == stage_id]


@dataclass(frozen=True)
class OpportunityDraft:
    organization_id: str
    product_lane: ProductLane
    stage_id: str
    title: str | None = None
    owner_actor_id: str | None = None
    estimated_value: float | None = None
    currency: str | None = None
    probability: float | None = None
    next_action_at: datetime | None = None
    next_action_note: str | None = None


@dataclass(frozen=True)
class OpportunityEdit:
    """Editable details of an existing opportunity (lane and stage change elsewhere)."""

    title: str | None = None
    owner_actor_id: str | None = None
    estimated_value: float | None = None
    currency: str | None = None
    probability: float | None = None
    next_action_at: datetime | None = None
    next_action_note: str | None = None


@dataclass(frozen=True)
class ActivityInfo:
    id: str
    type: ActivityType
    occurred_at: datetime
    summary: str
    contact_name: str | None
    actor_name: str | None
    voided: bool = False


@dataclass(frozen=True)
class TaskInfo:
    id: str
    title: str
    due_at: datetime | None
    completed_at: datetime | None
    opportunity_id: str | None
    organization_name: str | None = None
    opportunity_title: str | None = None

    @property
    def done(self) -> bool:
        return self.completed_at is not None


@dataclass(frozen=True)
class ContactChoice:
    id: str
    label: str
    email: str | None


@dataclass(frozen=True)
class ActorInfo:
    id: str
    name: str


@dataclass(frozen=True)
class OpportunityDetail:
    card: OpportunityCard
    stage: StageInfo
    owner_actor_id: str | None
    estimated_value: float | None
    currency: str | None
    probability: float | None
    outcome_reason_code: str | None
    outcome_reason: str | None
    closed_at: datetime | None
    created_at: datetime
    contacts: tuple[ContactChoice, ...]
    activities: tuple[ActivityInfo, ...]
    tasks: tuple[TaskInfo, ...]
    organization_website: str | None = None
    games: tuple[str, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class Reminder:
    """Something due: an opportunity's next action or an open task."""

    kind: str  # "next_action" or "task"
    due_at: datetime
    title: str
    organization_name: str
    opportunity_id: str | None
    task_id: str | None
    overdue: bool
