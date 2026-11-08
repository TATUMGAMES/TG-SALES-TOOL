"""Pipeline state at any past moment, reconstructed from the activity ledger."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from tg_sales.domain.enums import ProductLane
from tg_sales.domain.pipeline import apply_corrections, stage_counts, stages_as_of
from tg_sales.domain.time import ensure_utc
from tg_sales.repositories.activities import ActivityRepository
from tg_sales.repositories.opportunities import OpportunityRepository


class PipelineHistory:
    def __init__(self, session: Session) -> None:
        self._activities = ActivityRepository(session)
        self._opportunities = OpportunityRepository(session)

    def stages_as_of(self, as_of: datetime, *, lane: ProductLane | None = None) -> dict[str, str]:
        """Map each opportunity that existed at ``as_of`` to its stage at that moment.

        Opportunities deleted at or before ``as_of`` are excluded.
        """
        moment = ensure_utc(as_of)
        corrections = self._activities.corrections()
        # Events moved by a correction are read even if their original time is
        # after the moment, because the corrected time may fall inside it.
        retimed = {c.corrects_event_id for c in corrections if c.occurred_at is not None}
        events = self._activities.stage_events(lane, occurred_until=moment, also_include=retimed)
        stages = stages_as_of(apply_corrections(events, corrections), moment)
        deleted = self._opportunities.deleted_at_or_before(moment)
        return {opp: stage for opp, stage in stages.items() if opp not in deleted}

    def stage_counts_as_of(
        self, as_of: datetime, *, lane: ProductLane | None = None
    ) -> dict[str, int]:
        return dict(stage_counts(self.stages_as_of(as_of, lane=lane)))

    def stage_of(self, opportunity_id: str, as_of: datetime) -> str | None:
        return self.stages_as_of(as_of).get(opportunity_id)
