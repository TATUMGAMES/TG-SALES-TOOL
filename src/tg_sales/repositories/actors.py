"""People who own opportunities and perform activities."""

from __future__ import annotations

from sqlalchemy.orm import Session

from tg_sales.db.models import Actor


class ActorRepository:
    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, actor_id: str) -> Actor | None:
        actor = self._session.get(Actor, actor_id)
        return None if actor is None or actor.is_deleted else actor

    def add(self, display_name: str) -> Actor:
        actor = Actor(display_name=display_name)
        self._session.add(actor)
        self._session.flush()
        return actor
