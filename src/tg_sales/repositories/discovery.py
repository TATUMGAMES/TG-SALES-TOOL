"""Discovery runs, the review queue, and lookups against games already in the CRM."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from tg_sales.db.models import DiscoveryLead, DiscoveryRun, Game, GameOrganization, Organization


class DiscoveryRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def add_run(self, run: DiscoveryRun) -> DiscoveryRun:
        self._session.add(run)
        self._session.flush()
        return run

    def get_run(self, run_id: str) -> DiscoveryRun | None:
        return self._session.get(DiscoveryRun, run_id)

    def latest_run(self, source: str, *, successful: bool = False) -> DiscoveryRun | None:
        query = select(DiscoveryRun).where(
            DiscoveryRun.source == source, DiscoveryRun.deleted_at_utc.is_(None)
        )
        if successful:
            query = query.where(DiscoveryRun.status == "completed")
        return self._session.scalar(
            query.order_by(DiscoveryRun.started_at_utc.desc(), DiscoveryRun.id.desc()).limit(1)
        )

    def lead(self, lead_id: str) -> DiscoveryLead | None:
        lead = self._session.get(DiscoveryLead, lead_id)
        return None if lead is None or lead.is_deleted else lead

    def lead_by_external(self, source: str, external_id: str) -> DiscoveryLead | None:
        return self._session.scalar(
            select(DiscoveryLead).where(
                DiscoveryLead.source == source,
                DiscoveryLead.external_id == external_id,
                DiscoveryLead.deleted_at_utc.is_(None),
            )
        )

    def add_lead(self, lead: DiscoveryLead) -> DiscoveryLead:
        self._session.add(lead)
        self._session.flush()
        return lead

    def leads(self) -> list[DiscoveryLead]:
        return list(
            self._session.scalars(
                select(DiscoveryLead)
                .where(DiscoveryLead.deleted_at_utc.is_(None))
                .order_by(DiscoveryLead.last_checked_at_utc.desc(), DiscoveryLead.id)
            )
        )

    def games_in_crm(self, store: str, store_ids: Collection[str]) -> dict[str, tuple[str, str]]:
        """Map store ids already in the CRM to (organization id, organization name)."""
        if not store_ids:
            return {}
        result: dict[str, tuple[str, str]] = {}
        ids = list(store_ids)
        for offset in range(0, len(ids), 900):
            rows = self._session.execute(
                select(Game.store_id, Organization.id, Organization.name)
                .join(GameOrganization, GameOrganization.game_id == Game.id)
                .join(Organization, Organization.id == GameOrganization.organization_id)
                .where(
                    Game.store == store,
                    Game.store_id.in_(ids[offset : offset + 900]),
                    Game.deleted_at_utc.is_(None),
                    GameOrganization.deleted_at_utc.is_(None),
                    Organization.deleted_at_utc.is_(None),
                )
            )
            for store_id, org_id, name in rows:
                result.setdefault(str(store_id), (org_id, name))
        return result

    def game_by_store_id(self, store: str, store_id: str) -> Game | None:
        return self._session.scalar(
            select(Game).where(
                Game.store == store, Game.store_id == store_id, Game.deleted_at_utc.is_(None)
            )
        )
