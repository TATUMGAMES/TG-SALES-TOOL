"""Opportunities."""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from tg_sales.db.models import Opportunity


class OpportunityRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, opportunity_id: str) -> Opportunity | None:
        opportunity = self._session.get(Opportunity, opportunity_id)
        return None if opportunity is None or opportunity.is_deleted else opportunity

    def add(self, opportunity: Opportunity) -> Opportunity:
        self._session.add(opportunity)
        self._session.flush()
        return opportunity

    def deleted_at_or_before(self, as_of: datetime) -> set[str]:
        """Ids of opportunities whose tombstone time is at or before ``as_of``."""
        rows = self._session.scalars(
            select(Opportunity.id).where(
                Opportunity.deleted_at_utc.is_not(None),
                Opportunity.deleted_at_utc <= as_of,
            )
        )
        return set(rows)
