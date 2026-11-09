# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

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
