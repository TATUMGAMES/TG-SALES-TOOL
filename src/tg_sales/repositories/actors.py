# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

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
