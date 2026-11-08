"""Pipeline stages."""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from tg_sales.db.models import PipelineStage


class StageRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, stage_id: str) -> PipelineStage | None:
        stage = self._session.get(PipelineStage, stage_id)
        return None if stage is None or stage.is_deleted else stage

    def list(self, *, include_archived: bool = False) -> Sequence[PipelineStage]:
        query = select(PipelineStage).where(PipelineStage.deleted_at_utc.is_(None))
        if not include_archived:
            query = query.where(PipelineStage.archived_at_utc.is_(None))
        return self._session.scalars(
            query.order_by(PipelineStage.sort_order, PipelineStage.name, PipelineStage.id)
        ).all()
