"""Pipeline use cases: stages, the board, opportunities, logged interactions and tasks.

Stage identifiers never change, so renaming or reordering stages never affects
history or reports. Archiving a stage first moves its opportunities to another
stage, writing a normal stage-change event for each. Every change is recorded
in the activity ledger in the same transaction.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta

from sqlalchemy.orm import Session

from tg_sales.db.database import Database
from tg_sales.db.models import Activity, Opportunity, PipelineStage, Task
from tg_sales.domain.enums import ActivityType, ProductLane, StageOutcome
from tg_sales.domain.handoff import HandoffDraft
from tg_sales.domain.normalization import normalize_email
from tg_sales.domain.opportunities import (
    LOGGABLE_TYPES,
    MAX_STAGE_NAME_LENGTH,
    REASON_CODES,
    ActivityInfo,
    ActorInfo,
    Board,
    ContactChoice,
    OpportunityCard,
    OpportunityDetail,
    OpportunityDraft,
    OpportunityEdit,
    Reminder,
    StageInfo,
    TaskInfo,
    contact_status_after,
    reason_label,
)
from tg_sales.domain.time import ensure_utc, format_utc, to_local
from tg_sales.errors import TgSalesError
from tg_sales.repositories.actors import ActorRepository
from tg_sales.repositories.opportunities import OpportunityRepository
from tg_sales.repositories.pipeline import PipelineRepository
from tg_sales.repositories.prospects import ContactRepository, OrganizationRepository
from tg_sales.repositories.stages import StageRepository
from tg_sales.services.ledger import ActivityLedger
from tg_sales.services.opportunities import OpportunityService
from tg_sales.services.timeline import summarize

# Logged interactions may be dated slightly ahead to absorb clock differences.
FUTURE_TOLERANCE = timedelta(minutes=5)
MAX_TEXT_LENGTH = 20_000


class PipelineError(TgSalesError):
    """A pipeline change was refused; nothing was saved."""


def _refuse(message: str, action: str) -> PipelineError:
    return PipelineError(message, action=action)


def _clean(text: str | None, limit: int = MAX_TEXT_LENGTH) -> str | None:
    if text is None:
        return None
    cleaned = text.replace("\x00", "").strip()
    return cleaned[:limit] if cleaned else None


def _stage_info(stage: PipelineStage, count: int = 0) -> StageInfo:
    return StageInfo(
        id=stage.id,
        name=stage.name,
        sort_order=stage.sort_order,
        product_lane=stage.product_lane,
        outcome=stage.outcome,
        archived=stage.archived_at_utc is not None,
        opportunity_count=count,
    )


def _json(value: object) -> object:
    if isinstance(value, datetime):
        return format_utc(value)
    return value


class PipelineService:
    def __init__(self, database: Database, actor_id: str | None) -> None:
        self._database = database
        self._actor_id = actor_id

    def _ledger(self, session: Session) -> ActivityLedger:
        return ActivityLedger(session, self._actor_id, self._database.clock)

    def _now(self) -> datetime:
        return self._database.clock.now()

    # -- stages -------------------------------------------------------------

    def stages(self, *, include_archived: bool = False) -> list[StageInfo]:
        with self._database.session() as session:
            counts = PipelineRepository(session).stage_counts()
            return [
                _stage_info(s, counts.get(s.id, 0))
                for s in StageRepository(session).list(include_archived=include_archived)
            ]

    def _validated_stage_name(
        self, session: Session, name: str, lane: ProductLane | None, exclude_id: str | None
    ) -> str:
        cleaned = _clean(name, MAX_STAGE_NAME_LENGTH)
        if cleaned is None:
            raise _refuse("A stage needs a name.", "Type a short stage name.")
        for stage in StageRepository(session).list():
            if (
                stage.id != exclude_id
                and stage.name.casefold() == cleaned.casefold()
                and (stage.product_lane is None or lane is None or stage.product_lane is lane)
            ):
                raise _refuse(
                    f"A stage called “{cleaned}” already exists.",
                    "Choose a different name so stages can be told apart.",
                )
        return cleaned

    def _record_stage_change(
        self, session: Session, stage: PipelineStage, changes: dict[str, dict[str, object]]
    ) -> None:
        self._ledger(session).record(
            ActivityType.FIELD_CHANGE,
            payload={"entity": "pipeline_stages", "entity_id": stage.id, "changes": changes},
        )

    def create_stage(
        self,
        name: str,
        outcome: StageOutcome = StageOutcome.OPEN,
        lane: ProductLane | None = None,
        *,
        after_stage_id: str | None = None,
    ) -> str:
        with self._database.session() as session:
            cleaned = self._validated_stage_name(session, name, lane, None)
            ordered = list(StageRepository(session).list())
            position = len(ordered)
            if after_stage_id is not None:
                position = next(
                    (i + 1 for i, s in enumerate(ordered) if s.id == after_stage_id), position
                )
            stage = PipelineStage(name=cleaned, sort_order=0, product_lane=lane, outcome=outcome)
            session.add(stage)
            session.flush()
            ordered.insert(position, stage)
            self._renumber(ordered)
            self._record_stage_change(session, stage, {"created": {"old": None, "new": cleaned}})
            return stage.id

    @staticmethod
    def _renumber(stages: Sequence[PipelineStage]) -> None:
        for index, stage in enumerate(stages, start=1):
            if stage.sort_order != index * 10:
                stage.sort_order = index * 10

    def rename_stage(self, stage_id: str, name: str) -> bool:
        with self._database.session() as session:
            stage = self._existing_stage(session, stage_id)
            cleaned = self._validated_stage_name(session, name, stage.product_lane, stage.id)
            if cleaned == stage.name:
                return False
            old = stage.name
            stage.name = cleaned
            self._record_stage_change(session, stage, {"name": {"old": old, "new": cleaned}})
            return True

    def reorder_stages(self, stage_ids: Sequence[str]) -> None:
        """Set the display order of the active stages (ids in the new order)."""
        with self._database.session() as session:
            active = {s.id: s for s in StageRepository(session).list()}
            if set(stage_ids) != set(active) or len(stage_ids) != len(active):
                raise _refuse(
                    "The stage list changed while you were editing it.",
                    "Close and reopen Manage stages, then try again.",
                )
            ordered = [active[i] for i in stage_ids]
            before = {s.id: s.sort_order for s in ordered}
            self._renumber(ordered)
            moved = [s for s in ordered if s.sort_order != before[s.id]]
            if moved:
                self._ledger(session).record(
                    ActivityType.FIELD_CHANGE,
                    payload={
                        "entity": "pipeline_stages",
                        "entity_id": None,
                        "changes": {"order": {"old": None, "new": list(stage_ids)}},
                    },
                )

    def move_stage(self, stage_id: str, offset: int) -> None:
        """Move a stage up (negative) or down (positive) in the display order."""
        ids = [s.id for s in self.stages()]
        if stage_id not in ids:
            raise _refuse("This stage is not active.", "Restore it first.")
        index = ids.index(stage_id)
        target = max(0, min(len(ids) - 1, index + offset))
        ids.insert(target, ids.pop(index))
        self.reorder_stages(ids)

    def set_stage_outcome(self, stage_id: str, outcome: StageOutcome) -> bool:
        """Change what reaching a stage means; refused while it holds opportunities."""
        with self._database.session() as session:
            stage = self._existing_stage(session, stage_id)
            if stage.outcome is outcome:
                return False
            if PipelineRepository(session).opportunities_in_stage(stage.id):
                raise _refuse(
                    f"“{stage.name}” has opportunities, so its outcome cannot change.",
                    "Move its opportunities to other stages first, or create a new stage.",
                )
            if stage.outcome is StageOutcome.OPEN and outcome is not StageOutcome.OPEN:
                self._ensure_other_open_stage(session, stage)
            old = stage.outcome
            stage.outcome = outcome
            self._record_stage_change(
                session, stage, {"outcome": {"old": old.value, "new": outcome.value}}
            )
            return True

    def _ensure_other_open_stage(self, session: Session, stage: PipelineStage) -> None:
        others = [
            s
            for s in StageRepository(session).list()
            if s.id != stage.id and s.outcome is StageOutcome.OPEN and s.product_lane is None
        ]
        if not others:
            raise _refuse(
                "At least one open stage for all product lanes must remain.",
                "Create another open stage first.",
            )

    def archive_stage(self, stage_id: str, move_to_stage_id: str | None) -> int:
        """Archive a stage, first moving its opportunities; returns how many moved."""
        with self._database.session() as session:
            stage = self._existing_stage(session, stage_id)
            if stage.archived_at_utc is not None:
                return 0
            if stage.outcome is StageOutcome.OPEN and stage.product_lane is None:
                self._ensure_other_open_stage(session, stage)
            opportunities = PipelineRepository(session).opportunities_in_stage(stage.id)
            target: PipelineStage | None = None
            if opportunities:
                if move_to_stage_id is None or move_to_stage_id == stage.id:
                    raise _refuse(
                        f"“{stage.name}” has {len(opportunities)} opportunities.",
                        "Choose the stage they should move to.",
                    )
                target = self._existing_stage(session, move_to_stage_id)
                if target.archived_at_utc is not None:
                    raise _refuse("That stage is archived.", "Choose an active stage.")
                mover = OpportunityService(session, self._ledger(session), self._database.clock)
                reason = f"Stage “{stage.name}” archived"
                code = "other" if target.is_terminal else None
                for opportunity in opportunities:
                    if (
                        target.product_lane is not None
                        and target.product_lane is not opportunity.product_lane
                    ):
                        raise _refuse(
                            f"“{target.name}” belongs to another product lane.",
                            "Choose a stage available to all of this stage's opportunities.",
                        )
                    mover.move_to_stage(opportunity.id, target.id, reason=reason, reason_code=code)
            stage.archived_at_utc = self._now()
            self._record_stage_change(
                session,
                stage,
                {
                    "archived_at_utc": {"old": None, "new": format_utc(stage.archived_at_utc)},
                    **({"moved_to": {"old": None, "new": target.id}} if target else {}),
                },
            )
            return len(opportunities)

    def restore_stage(self, stage_id: str) -> bool:
        with self._database.session() as session:
            stage = self._existing_stage(session, stage_id)
            if stage.archived_at_utc is None:
                return False
            self._validated_stage_name(session, stage.name, stage.product_lane, stage.id)
            old = format_utc(stage.archived_at_utc)
            stage.archived_at_utc = None
            ordered = [s for s in StageRepository(session).list() if s.id != stage.id]
            ordered.append(stage)
            self._renumber(ordered)
            self._record_stage_change(
                session, stage, {"archived_at_utc": {"old": old, "new": None}}
            )
            return True

    def _existing_stage(self, session: Session, stage_id: str) -> PipelineStage:
        stage = StageRepository(session).get(stage_id)
        if stage is None:
            raise _refuse("This stage no longer exists.", "Refresh the pipeline and try again.")
        return stage

    # -- board --------------------------------------------------------------

    def board(self, lane: ProductLane | None = None) -> Board:
        with self._database.session() as session:
            stages = [
                _stage_info(s)
                for s in StageRepository(session).list()
                if lane is None or s.product_lane is None or s.product_lane is lane
            ]
            cards = self._cards(session, lane)
            visible = {s.id for s in stages}
            return Board(tuple(stages), tuple(c for c in cards if c.stage_id in visible))

    def _cards(
        self, session: Session, lane: ProductLane | None, opportunity_id: str | None = None
    ) -> list[OpportunityCard]:
        repo = PipelineRepository(session)
        rows = repo.board_rows(lane, opportunity_id)
        opportunities = [row[0] for row in rows]
        last = repo.last_activity([o.id for o in opportunities])
        today = to_local(self._now()).date()
        releases = repo.release_dates({o.organization_id for o in opportunities}, today)
        return [
            OpportunityCard(
                id=opp.id,
                organization_id=opp.organization_id,
                organization_name=org_name,
                title=opp.title,
                product_lane=opp.product_lane,
                stage_id=opp.stage_id,
                owner_name=owner,
                last_activity_at=last.get(opp.id),
                next_action_at=opp.next_action_at_utc,
                next_action_note=opp.next_action_note,
                release_date=releases.get(opp.organization_id),
                closed=bool(closed),
            )
            for opp, org_name, owner, closed in rows
        ]

    # -- opportunities ------------------------------------------------------

    @staticmethod
    def _validated_numbers(
        value: float | None, currency: str | None, probability: float | None
    ) -> str | None:
        if value is not None and value < 0:
            raise _refuse("The estimated value cannot be negative.", "Enter 0 or more.")
        if probability is not None and not 0 <= probability <= 1:
            raise _refuse("The probability must be between 0 % and 100 %.", "Correct it.")
        code = _clean(currency)
        if code is not None:
            code = code.upper()
            if len(code) != 3 or not code.isalpha():
                raise _refuse(
                    f"“{code}” is not a currency code.", "Use a three-letter code such as USD."
                )
        return code

    def create_opportunity(self, draft: OpportunityDraft) -> str:
        currency = self._validated_numbers(draft.estimated_value, draft.currency, draft.probability)
        with self._database.session() as session:
            if OrganizationRepository(session).get(draft.organization_id) is None:
                raise _refuse("That prospect no longer exists.", "Choose another prospect.")
            service = OpportunityService(session, self._ledger(session), self._database.clock)
            try:
                opportunity = service.create(
                    organization_id=draft.organization_id,
                    product_lane=draft.product_lane,
                    stage_id=draft.stage_id,
                    owner_actor_id=draft.owner_actor_id or self._actor_id,
                    title=_clean(draft.title, 200),
                )
            except ValueError as exc:
                raise _refuse(
                    "That stage cannot be used for this product lane.",
                    "Choose a stage shown for the selected lane.",
                ) from exc
            opportunity.estimated_value = draft.estimated_value
            opportunity.currency = currency
            opportunity.probability = draft.probability
            if draft.next_action_at is not None:
                opportunity.next_action_at_utc = ensure_utc(draft.next_action_at)
            opportunity.next_action_note = _clean(draft.next_action_note, 500)
            return opportunity.id

    def move(
        self,
        opportunity_id: str,
        stage_id: str,
        *,
        reason_code: str | None = None,
        reason_note: str | None = None,
    ) -> bool:
        """Move an opportunity to a stage; terminal stages require a reason code."""
        with self._database.session() as session:
            stage = self._existing_stage(session, stage_id)
            if stage.archived_at_utc is not None:
                raise _refuse(f"“{stage.name}” is archived.", "Choose an active stage.")
            if stage.is_terminal:
                codes = {code for code, _ in REASON_CODES[stage.outcome]}
                if reason_code not in codes:
                    raise _refuse(
                        f"Moving to “{stage.name}” needs a reason.",
                        "Choose why the opportunity was won, lost or not a fit.",
                    )
            opportunity = OpportunityRepository(session).get(opportunity_id)
            if opportunity is None:
                raise _refuse("This opportunity no longer exists.", "Refresh the pipeline.")
            service = OpportunityService(session, self._ledger(session), self._database.clock)
            try:
                event = service.move_to_stage(
                    opportunity.id,
                    stage.id,
                    reason=_clean(reason_note, 500)
                    or (reason_label(stage.outcome, reason_code) if stage.is_terminal else None),
                    reason_code=reason_code if stage.is_terminal else None,
                )
            except ValueError as exc:
                raise _refuse(
                    f"“{stage.name}” is not available for this opportunity's product lane.",
                    "Choose a stage shown for its lane.",
                ) from exc
            return event is not None

    def update(self, opportunity_id: str, edit: OpportunityEdit) -> bool:
        currency = self._validated_numbers(edit.estimated_value, edit.currency, edit.probability)
        values: dict[str, object] = {
            "title": _clean(edit.title, 200),
            "owner_actor_id": edit.owner_actor_id,
            "estimated_value": edit.estimated_value,
            "currency": currency,
            "probability": edit.probability,
            "next_action_at_utc": None
            if edit.next_action_at is None
            else ensure_utc(edit.next_action_at),
            "next_action_note": _clean(edit.next_action_note, 500),
        }
        with self._database.session() as session:
            opportunity = OpportunityRepository(session).get(opportunity_id)
            if opportunity is None:
                raise _refuse("This opportunity no longer exists.", "Refresh the pipeline.")
            if edit.owner_actor_id and ActorRepository(session).get(edit.owner_actor_id) is None:
                raise _refuse("That owner no longer exists.", "Choose another owner.")
            changes: dict[str, dict[str, object]] = {}
            for name, new in values.items():
                old = getattr(opportunity, name)
                if old != new:
                    changes[name] = {"old": _json(old), "new": _json(new)}
                    setattr(opportunity, name, new)
            if changes:
                self._ledger(session).record(
                    ActivityType.FIELD_CHANGE,
                    organization_id=opportunity.organization_id,
                    opportunity_id=opportunity.id,
                    payload={
                        "entity": "opportunities",
                        "entity_id": opportunity.id,
                        "changes": changes,
                    },
                )
            return bool(changes)

    def detail(self, opportunity_id: str) -> OpportunityDetail | None:
        with self._database.session() as session:
            cards = self._cards(session, None, opportunity_id)
            opportunity = OpportunityRepository(session).get(opportunity_id)
            if not cards or opportunity is None:
                return None
            card = cards[0]
            stages = {s.id: s for s in StageRepository(session).list(include_archived=True)}
            stage = stages[opportunity.stage_id]
            repo = PipelineRepository(session)
            contacts = repo.contacts(opportunity.organization_id)
            contact_names = {c.id: c.name or c.business_email or "Contact" for c in contacts}
            actors = {a.id: a.display_name for a in repo.actors()}
            activities = repo.opportunity_activities(opportunity.id)
            voided = repo.voided_event_ids([a.id for a in activities])
            stage_names = {s.id: s.name for s in stages.values()}
            organization = OrganizationRepository(session).get(opportunity.organization_id)
            return OpportunityDetail(
                card=card,
                stage=_stage_info(stage),
                owner_actor_id=opportunity.owner_actor_id,
                estimated_value=opportunity.estimated_value,
                currency=opportunity.currency,
                probability=opportunity.probability,
                outcome_reason_code=opportunity.outcome_reason_code,
                outcome_reason=opportunity.outcome_reason,
                closed_at=opportunity.closed_at_utc,
                created_at=opportunity.created_at_utc,
                contacts=tuple(
                    ContactChoice(
                        c.id,
                        (c.name or c.business_email or "Contact")
                        + (f" ({c.role_title})" if c.role_title else ""),
                        c.business_email,
                    )
                    for c in contacts
                ),
                activities=tuple(
                    ActivityInfo(
                        id=a.id,
                        type=a.type,
                        occurred_at=a.occurred_at_utc,
                        summary=summarize(a, stage_names),
                        contact_name=contact_names.get(a.contact_id or ""),
                        actor_name=actors.get(a.actor_id or ""),
                        voided=a.id in voided,
                    )
                    for a in activities
                    if a.type is not ActivityType.CORRECTION
                ),
                tasks=tuple(self._task_info(t) for t in repo.tasks_for(opportunity.id)),
                organization_website=organization.website if organization else None,
            )

    @staticmethod
    def _task_info(task: Task, org: str | None = None, title: str | None = None) -> TaskInfo:
        return TaskInfo(
            id=task.id,
            title=task.title,
            due_at=task.due_at_utc,
            completed_at=task.completed_at_utc,
            opportunity_id=task.opportunity_id,
            organization_name=org,
            opportunity_title=title,
        )

    def _live_opportunity(self, session: Session, opportunity_id: str) -> Opportunity:
        opportunity = OpportunityRepository(session).get(opportunity_id)
        if opportunity is None:
            raise _refuse("This opportunity no longer exists.", "Refresh the pipeline.")
        return opportunity

    # -- interactions -------------------------------------------------------

    def log_activity(
        self,
        opportunity_id: str,
        activity_type: ActivityType,
        *,
        occurred_at: datetime | None = None,
        contact_id: str | None = None,
        note: str | None = None,
    ) -> str:
        """Record an interaction the salesperson reports (nothing is sent)."""
        if activity_type not in LOGGABLE_TYPES:
            raise _refuse("This kind of activity cannot be logged here.", "Choose another type.")
        now = self._now()
        when = now if occurred_at is None else ensure_utc(occurred_at)
        if when > now + FUTURE_TOLERANCE:
            raise _refuse(
                "An interaction cannot be logged in the future.",
                "Use a date and time that has already passed, or add a task instead.",
            )
        with self._database.session() as session:
            opportunity = self._live_opportunity(session, opportunity_id)
            ledger = self._ledger(session)
            contact = None
            if contact_id is not None:
                contact = ContactRepository(session).get(contact_id)
                if contact is None or contact.organization_id != opportunity.organization_id:
                    raise _refuse(
                        "That contact does not belong to this prospect.", "Choose another contact."
                    )
            event = ledger.record(
                activity_type,
                occurred_at=when,
                organization_id=opportunity.organization_id,
                opportunity_id=opportunity.id,
                contact_id=contact_id,
                payload={"note": _clean(note, 2000), "logged_manually": True},
            )
            if contact is not None:
                new_status = contact_status_after(contact.contact_status, activity_type)
                if new_status is not contact.contact_status:
                    old = contact.contact_status
                    contact.contact_status = new_status
                    ledger.record(
                        ActivityType.FIELD_CHANGE,
                        organization_id=opportunity.organization_id,
                        contact_id=contact.id,
                        payload={
                            "entity": "contacts",
                            "entity_id": contact.id,
                            "changes": {
                                "contact_status": {"old": old.value, "new": new_status.value}
                            },
                        },
                    )
            return event.id

    def add_note(self, opportunity_id: str, text: str) -> None:
        cleaned = _clean(text)
        if cleaned is None:
            raise _refuse("The note is empty.", "Type a note first.")
        with self._database.session() as session:
            opportunity = self._live_opportunity(session, opportunity_id)
            self._ledger(session).record(
                ActivityType.NOTE,
                organization_id=opportunity.organization_id,
                opportunity_id=opportunity.id,
                payload={"text": cleaned},
            )

    def void_activity(self, activity_id: str, reason: str) -> None:
        """Mark a logged interaction as a mistake (the original is kept)."""
        with self._database.session() as session:
            original = session.get(Activity, activity_id)
            if original is None or original.type not in LOGGABLE_TYPES | {ActivityType.NOTE}:
                raise _refuse("Only logged interactions and notes can be voided.", "Choose one.")
            self._ledger(session).correct(
                original.id, reason=reason or "Logged by mistake", void=True
            )

    # -- tasks --------------------------------------------------------------

    def add_task(self, opportunity_id: str, title: str, due_at: datetime | None) -> str:
        cleaned = _clean(title, 300)
        if cleaned is None:
            raise _refuse("A task needs a description.", "Describe what needs to be done.")
        with self._database.session() as session:
            opportunity = self._live_opportunity(session, opportunity_id)
            task = PipelineRepository(session).add_task(
                Task(
                    opportunity_id=opportunity.id,
                    organization_id=opportunity.organization_id,
                    assignee_actor_id=self._actor_id,
                    title=cleaned,
                    due_at_utc=None if due_at is None else ensure_utc(due_at),
                )
            )
            self._ledger(session).record(
                ActivityType.TASK_CREATED,
                organization_id=opportunity.organization_id,
                opportunity_id=opportunity.id,
                payload={"task_id": task.id, "title": cleaned},
            )
            return task.id

    def set_task_done(self, task_id: str, done: bool) -> bool:
        with self._database.session() as session:
            task = PipelineRepository(session).get_task(task_id)
            if task is None:
                raise _refuse("This task no longer exists.", "Refresh and try again.")
            if (task.completed_at_utc is not None) == done:
                return False
            task.completed_at_utc = self._now() if done else None
            if done:
                self._ledger(session).record(
                    ActivityType.TASK_COMPLETED,
                    organization_id=task.organization_id,
                    opportunity_id=task.opportunity_id,
                    payload={"task_id": task.id, "title": task.title},
                )
            else:
                self._ledger(session).record(
                    ActivityType.FIELD_CHANGE,
                    organization_id=task.organization_id,
                    opportunity_id=task.opportunity_id,
                    payload={
                        "entity": "tasks",
                        "entity_id": task.id,
                        "changes": {"completed_at_utc": {"old": "done", "new": None}},
                    },
                )
            return True

    # -- reminders and lookups ------------------------------------------------

    def reminders(self, until: datetime) -> list[Reminder]:
        """Next actions and open tasks due at or before ``until``, earliest first."""
        now = self._now()
        limit = ensure_utc(until)
        with self._database.session() as session:
            repo = PipelineRepository(session)
            items = [
                Reminder(
                    "next_action",
                    opp.next_action_at_utc,
                    opp.next_action_note or opp.title or "Next action",
                    org_name,
                    opp.id,
                    None,
                    opp.next_action_at_utc < now,
                )
                for opp, org_name in repo.next_actions_due(limit)
                if opp.next_action_at_utc is not None
            ]
            items += [
                Reminder(
                    "task",
                    task.due_at_utc,
                    task.title,
                    org_name or "",
                    task.opportunity_id,
                    task.id,
                    task.due_at_utc < now,
                )
                for task, org_name, _title in repo.open_tasks_due(limit)
                if task.due_at_utc is not None
            ]
        return sorted(items, key=lambda r: (r.due_at, r.kind, r.title))

    def actors(self) -> list[ActorInfo]:
        with self._database.session() as session:
            return [ActorInfo(a.id, a.display_name) for a in PipelineRepository(session).actors()]

    def organization_choices(self, text: str = "") -> list[tuple[str, str]]:
        with self._database.session() as session:
            return PipelineRepository(session).organization_choices(text)

    @property
    def actor_id(self) -> str | None:
        return self._actor_id

    def now(self) -> datetime:
        """The current time from the application clock (used for overdue display)."""
        return self._now()

    def opportunity_count(self) -> int:
        with self._database.session() as session:
            return sum(PipelineRepository(session).stage_counts().values())

    # -- technical handoff ----------------------------------------------------

    def handoff_draft(self, opportunity_id: str, contact_id: str | None = None) -> HandoffDraft:
        detail = self.detail(opportunity_id)
        if detail is None:
            raise _refuse("This opportunity no longer exists.", "Refresh the pipeline.")
        if detail.card.product_lane is not ProductLane.DATA_LICENSING:
            raise _refuse(
                "Technical handoffs are for data-licensing opportunities.",
                "Open a data-licensing opportunity to prepare a handoff.",
            )
        contact = next((c for c in detail.contacts if c.id == contact_id), None) or (
            detail.contacts[0] if detail.contacts else None
        )
        contact_text = None
        if contact is not None:
            email = normalize_email(contact.email) if contact.email else None
            contact_text = contact.label + (f" <{email}>" if email else "")
        with self._database.session() as session:
            actor = ActorRepository(session).get(self._actor_id) if self._actor_id else None
        return HandoffDraft(
            recipient="",
            organization=detail.card.organization_name,
            website=detail.organization_website,
            contact=contact_text,
            opportunity=detail.card.title or "Data licensing",
            prepared_by=actor.display_name if actor else None,
        )

    def record_handoff(
        self, opportunity_id: str, recipient: str, *, contact_id: str | None = None
    ) -> str:
        """Log that a handoff draft was prepared and copied; it is not sent by tg_sales."""
        return self.log_activity(
            opportunity_id,
            ActivityType.TECHNICAL_HANDOFF,
            contact_id=contact_id,
            note=(
                f"Draft for {recipient.strip()} copied; send it from your email client."
                if recipient.strip()
                else "Draft copied; send it from your email client."
            ),
        )
