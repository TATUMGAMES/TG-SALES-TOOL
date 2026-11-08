"""Creating opportunities and moving them between stages.

The opportunity row holds the current stage for fast queries; every change is
also written to the activity ledger in the same transaction, which is the
source of truth for history.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from tg_sales.db.models import Activity, Opportunity, PipelineStage
from tg_sales.domain.enums import ActivityType, ProductLane, RecordSource
from tg_sales.domain.time import Clock, ensure_utc
from tg_sales.repositories.opportunities import OpportunityRepository
from tg_sales.repositories.stages import StageRepository
from tg_sales.services.ledger import ActivityLedger


class OpportunityService:
    def __init__(self, session: Session, ledger: ActivityLedger, clock: Clock) -> None:
        self._opportunities = OpportunityRepository(session)
        self._stages = StageRepository(session)
        self._ledger = ledger
        self._clock = clock

    def _usable_stage(self, stage_id: str, lane: ProductLane) -> PipelineStage:
        stage = self._stages.get(stage_id)
        if stage is None or stage.archived_at_utc is not None:
            raise ValueError(f"stage {stage_id} is not available")
        if stage.product_lane is not None and stage.product_lane is not lane:
            raise ValueError(f"stage {stage.name!r} belongs to another product lane")
        return stage

    def create(
        self,
        *,
        organization_id: str,
        product_lane: ProductLane,
        stage_id: str,
        owner_actor_id: str | None = None,
        title: str | None = None,
        occurred_at: datetime | None = None,
        source: RecordSource = RecordSource.MANUAL,
    ) -> Opportunity:
        occurred = ensure_utc(occurred_at) if occurred_at is not None else self._clock.now()
        stage = self._usable_stage(stage_id, product_lane)
        opportunity = self._opportunities.add(
            Opportunity(
                organization_id=organization_id,
                product_lane=product_lane,
                stage_id=stage.id,
                owner_actor_id=owner_actor_id,
                title=title,
                closed_at_utc=occurred if stage.is_terminal else None,
            )
        )
        self._ledger.record(
            ActivityType.OPPORTUNITY_CREATED,
            occurred_at=occurred,
            organization_id=organization_id,
            opportunity_id=opportunity.id,
            payload={
                "stage_id": stage.id,
                "product_lane": product_lane.value,
                "to_outcome": stage.outcome.value,
            },
            source=source,
        )
        return opportunity

    def move_to_stage(
        self,
        opportunity_id: str,
        stage_id: str,
        *,
        occurred_at: datetime | None = None,
        reason: str | None = None,
        reason_code: str | None = None,
    ) -> Activity | None:
        """Move an opportunity; returns the stage-change event, or None if unchanged.

        Reaching a terminal stage records the outcome reason; reopening clears it.
        """
        opportunity = self._opportunities.get(opportunity_id)
        if opportunity is None:
            raise ValueError(f"opportunity {opportunity_id} does not exist")
        if opportunity.stage_id == stage_id:
            return None
        stage = self._usable_stage(stage_id, opportunity.product_lane)
        occurred = ensure_utc(occurred_at) if occurred_at is not None else self._clock.now()
        previous_stage_id = opportunity.stage_id
        opportunity.stage_id = stage.id
        opportunity.closed_at_utc = occurred if stage.is_terminal else None
        opportunity.outcome_reason = reason if stage.is_terminal else None
        opportunity.outcome_reason_code = reason_code if stage.is_terminal else None
        return self._ledger.record(
            ActivityType.STAGE_CHANGE,
            occurred_at=occurred,
            organization_id=opportunity.organization_id,
            opportunity_id=opportunity.id,
            payload={
                "from_stage_id": previous_stage_id,
                "to_stage_id": stage.id,
                "to_outcome": stage.outcome.value,
                "reason": reason,
                "reason_code": reason_code,
            },
        )
