"""Message templates, their revisions and recorded outcomes."""

from __future__ import annotations

from collections.abc import Collection

from sqlalchemy import select
from sqlalchemy.orm import Session

from tg_sales.db.models import Actor, PlaybookOutcome, PlaybookRevision, PlaybookTemplate


class PlaybookRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, template_id: str) -> PlaybookTemplate | None:
        template = self._session.get(PlaybookTemplate, template_id)
        return None if template is None or template.is_deleted else template

    def all(self) -> list[PlaybookTemplate]:
        return list(
            self._session.scalars(
                select(PlaybookTemplate)
                .where(PlaybookTemplate.deleted_at_utc.is_(None))
                .order_by(PlaybookTemplate.title, PlaybookTemplate.id)
            )
        )

    def example_keys(self) -> set[str]:
        """Example keys already present, including archived ones."""
        return {
            key
            for key in self._session.scalars(
                select(PlaybookTemplate.example_key).where(
                    PlaybookTemplate.deleted_at_utc.is_(None),
                    PlaybookTemplate.example_key.is_not(None),
                )
            )
            if key
        }

    def add(self, row: PlaybookTemplate | PlaybookRevision | PlaybookOutcome) -> None:
        self._session.add(row)
        self._session.flush()

    def revisions(self, template_id: str) -> list[PlaybookRevision]:
        return list(
            self._session.scalars(
                select(PlaybookRevision)
                .where(
                    PlaybookRevision.template_id == template_id,
                    PlaybookRevision.deleted_at_utc.is_(None),
                )
                .order_by(PlaybookRevision.revision.desc())
            )
        )

    def revision(self, template_id: str, revision: int) -> PlaybookRevision | None:
        return self._session.scalar(
            select(PlaybookRevision).where(
                PlaybookRevision.template_id == template_id,
                PlaybookRevision.revision == revision,
                PlaybookRevision.deleted_at_utc.is_(None),
            )
        )

    def outcomes(self, template_id: str) -> list[PlaybookOutcome]:
        return list(
            self._session.scalars(
                select(PlaybookOutcome)
                .where(
                    PlaybookOutcome.template_id == template_id,
                    PlaybookOutcome.deleted_at_utc.is_(None),
                )
                .order_by(PlaybookOutcome.recorded_at_utc.desc(), PlaybookOutcome.id)
            )
        )

    def actor_names(self, actor_ids: Collection[str | None]) -> dict[str, str]:
        ids = sorted({a for a in actor_ids if a})
        if not ids:
            return {}
        rows = self._session.execute(select(Actor.id, Actor.display_name).where(Actor.id.in_(ids)))
        return {actor_id: name for actor_id, name in rows}
