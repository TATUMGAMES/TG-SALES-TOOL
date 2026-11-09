# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Use cases for the Playbook: message templates, revisions, outcomes, personalization.

Templates are shared data (they are included in sync and backups). Every saved
edit stores the full content as a new revision, so any earlier version can be
restored. Editing the title or message of an approved template removes the
approval: the changed text has not been approved yet.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
from datetime import date

from tg_sales.db.database import Database
from tg_sales.db.models import PlaybookOutcome, PlaybookRevision, PlaybookTemplate
from tg_sales.domain.playbook import (
    Channel,
    Outcome,
    OutcomeNote,
    Placeholder,
    PlaybookError,
    RevisionInfo,
    StaleRevisionError,
    TemplateDetail,
    TemplateDraft,
    TemplateFilters,
    TemplateSummary,
    change_summary,
    release_phrase,
)
from tg_sales.domain.playbook_examples import EXAMPLES
from tg_sales.domain.prospects import OrganizationDetail
from tg_sales.domain.time import to_local
from tg_sales.repositories.playbook import PlaybookRepository

COPY_PREFIX = "Copy of "


@dataclass(frozen=True, slots=True)
class Vocabulary:
    """Values already used, offered as suggestions in the editor and filters."""

    labels: tuple[str, ...]
    categories: tuple[str, ...]
    audiences: tuple[str, ...]
    stages: tuple[str, ...]
    tags: tuple[str, ...]


def _sorted_unique(values: list[str | None]) -> tuple[str, ...]:
    unique: dict[str, str] = {}
    for value in values:
        if value:
            unique.setdefault(value.casefold(), value)
    return tuple(sorted(unique.values(), key=str.casefold))


def _summary(row: PlaybookTemplate) -> TemplateSummary:
    try:
        channel = Channel(row.channel or Channel.EMAIL.value)
    except ValueError:
        channel = Channel.EMAIL
    return TemplateSummary(
        id=row.id,
        title=row.title,
        channel=channel,
        label=row.label,
        category=row.category,
        audience=row.audience,
        stage=row.stage,
        tags=tuple(row.tags or ()),
        is_favorite=row.is_favorite,
        is_approved=row.is_approved,
        revision=row.revision,
        updated_at=row.updated_at_utc,
        archived=row.archived_at_utc is not None,
        body=row.body,
    )


def default_choices(detail: OrganizationDetail, *, today: date) -> tuple[str | None, str | None]:
    """The contact and game used when the user has not chosen: the first named
    active contact, and the game with the nearest upcoming (else most recent)
    release."""
    contacts = [c for c in detail.contacts if not c.archived and c.name]
    contact_id = contacts[0].id if contacts else None
    game_id = None
    if detail.games:
        dated = [g for g in detail.games if g.release_date is not None]
        upcoming = sorted(
            (g for g in dated if g.release_date and g.release_date >= today),
            key=lambda g: g.release_date or today,
        )
        recent = sorted(dated, key=lambda g: g.release_date or today, reverse=True)
        game_id = (upcoming or recent or list(detail.games))[0].id
    return contact_id, game_id


def personalization_values(
    detail: OrganizationDetail | None,
    contact_id: str | None = None,
    game_id: str | None = None,
    *,
    today: date,
) -> dict[str, str | None]:
    """Placeholder values for a prospect.

    ``None`` for the contact or game means "use the default choice"; an empty
    string means "none".
    """
    values: dict[str, str | None] = {p.value: None for p in Placeholder}
    if detail is None:
        return values
    default_contact, default_game = default_choices(detail, today=today)
    contact_id = default_contact if contact_id is None else contact_id
    game_id = default_game if game_id is None else game_id
    values[Placeholder.STUDIO_NAME] = detail.name
    contact = next((c for c in detail.contacts if c.id == contact_id and c.name), None)
    if contact is not None:
        values[Placeholder.CONTACT_NAME] = contact.name
    game = next((g for g in detail.games if g.id == game_id), None)
    if game is not None:
        values[Placeholder.GAME_TITLE] = game.title
        values[Placeholder.PLATFORM] = game.platform
        values[Placeholder.RELEASE_DATE] = release_phrase(game.release_date, game.release_precision)
    return values


class PlaybookService:
    def __init__(self, database: Database, actor_id: str | None) -> None:
        self._database = database
        self._actor_id = actor_id

    # -- reading ------------------------------------------------------------

    def templates(self, filters: TemplateFilters | None = None) -> list[TemplateSummary]:
        """Matching templates: favorites first, then by title."""
        wanted = filters or TemplateFilters()
        with self._database.session() as session:
            rows = PlaybookRepository(session).all()
            summaries = [_summary(r) for r in rows]
        matches = [s for s in summaries if s.matches(wanted)]
        return sorted(matches, key=lambda s: (not s.is_favorite, s.title.casefold(), s.id))

    def count(self, *, include_archived: bool = False) -> int:
        with self._database.session() as session:
            rows = PlaybookRepository(session).all()
            return sum(1 for r in rows if include_archived or r.archived_at_utc is None)

    def vocabulary(self) -> Vocabulary:
        with self._database.session() as session:
            rows = PlaybookRepository(session).all()
            return Vocabulary(
                labels=_sorted_unique([r.label for r in rows]),
                categories=_sorted_unique([r.category for r in rows]),
                audiences=_sorted_unique([r.audience for r in rows]),
                stages=_sorted_unique([r.stage for r in rows]),
                tags=_sorted_unique([t for r in rows for t in (r.tags or ())]),
            )

    def get(self, template_id: str) -> TemplateDetail | None:
        with self._database.session() as session:
            repo = PlaybookRepository(session)
            row = repo.get(template_id)
            if row is None:
                return None
            revisions = repo.revisions(template_id)
            outcomes = repo.outcomes(template_id)
            names = repo.actor_names(
                [row.author_actor_id]
                + [r.author_actor_id for r in revisions]
                + [o.author_actor_id for o in outcomes]
            )
            return TemplateDetail(
                summary=_summary(row),
                notes=row.notes,
                author=names.get(row.author_actor_id or ""),
                created_at=row.created_at_utc,
                revisions=tuple(
                    RevisionInfo(
                        revision=r.revision,
                        created_at=r.created_at_utc,
                        author=names.get(r.author_actor_id or ""),
                        summary=r.summary,
                        content=TemplateDraft.from_content(r.content),
                    )
                    for r in revisions
                ),
                outcomes=tuple(
                    OutcomeNote(
                        id=o.id,
                        outcome=Outcome(o.outcome) if o.outcome in set(Outcome) else Outcome.OTHER,
                        note=o.note,
                        recorded_at=o.recorded_at_utc,
                        author=names.get(o.author_actor_id or ""),
                    )
                    for o in outcomes
                ),
                example_key=row.example_key,
            )

    # -- writing ------------------------------------------------------------

    def _existing(self, repo: PlaybookRepository, template_id: str) -> PlaybookTemplate:
        row = repo.get(template_id)
        if row is None:
            raise PlaybookError(
                "This template no longer exists.",
                action="It may have been deleted on another computer. Refresh the list.",
            )
        return row

    def _add_revision(self, repo: PlaybookRepository, row: PlaybookTemplate, summary: str) -> None:
        draft = TemplateDraft(
            title=row.title,
            body=row.body,
            channel=Channel(row.channel or Channel.EMAIL.value),
            label=row.label,
            category=row.category,
            audience=row.audience,
            stage=row.stage,
            notes=row.notes,
            tags=tuple(row.tags or ()),
        )
        repo.add(
            PlaybookRevision(
                template_id=row.id,
                revision=row.revision,
                content=draft.content(),
                summary=summary,
                author_actor_id=self._actor_id,
            )
        )

    @staticmethod
    def _apply(row: PlaybookTemplate, draft: TemplateDraft) -> None:
        row.title = draft.title
        row.body = draft.body
        row.channel = draft.channel.value
        row.label = draft.label
        row.category = draft.category
        row.audience = draft.audience
        row.stage = draft.stage
        row.notes = draft.notes
        row.tags = list(draft.tags)

    def create(
        self, draft: TemplateDraft, *, example_key: str | None = None, summary: str = "Created"
    ) -> str:
        clean = draft.validated()
        with self._database.session() as session:
            repo = PlaybookRepository(session)
            row = PlaybookTemplate(
                author_actor_id=self._actor_id,
                is_favorite=False,
                is_approved=False,
                revision=1,
                example_key=example_key,
                title="",
                body="",
                tags=[],
            )
            self._apply(row, clean)
            repo.add(row)
            self._add_revision(repo, row, summary)
            return row.id

    def _check_revision(self, row: PlaybookTemplate, expected_revision: int | None) -> None:
        if expected_revision is not None and row.revision != expected_revision:
            raise StaleRevisionError(
                "This template was changed since you opened it.",
                action="Close the editor, review the latest version, and make your change again.",
            )

    def update(
        self, template_id: str, draft: TemplateDraft, *, expected_revision: int | None = None
    ) -> bool:
        """Save an edit as a new revision. Returns False when nothing changed."""
        clean = draft.validated()
        with self._database.session() as session:
            repo = PlaybookRepository(session)
            row = self._existing(repo, template_id)
            self._check_revision(row, expected_revision)
            return self._save_content(repo, row, clean, None)

    def _save_content(
        self,
        repo: PlaybookRepository,
        row: PlaybookTemplate,
        new: TemplateDraft,
        summary: str | None,
    ) -> bool:
        old = TemplateDraft.from_content(
            {
                "title": row.title,
                "body": row.body,
                "channel": row.channel,
                "label": row.label,
                "category": row.category,
                "audience": row.audience,
                "stage": row.stage,
                "notes": row.notes,
                "tags": list(row.tags or ()),
            }
        )
        if old.content() == new.content():
            return False
        text = summary or change_summary(old, new)
        if row.is_approved and (old.title != new.title or old.body != new.body):
            row.is_approved = False
            text += "; approval removed because the text changed"
        self._apply(row, new)
        row.revision += 1
        self._add_revision(repo, row, text)
        return True

    def restore_revision(
        self, template_id: str, revision: int, *, expected_revision: int | None = None
    ) -> bool:
        """Make an earlier revision's content current again (as a new revision)."""
        with self._database.session() as session:
            repo = PlaybookRepository(session)
            row = self._existing(repo, template_id)
            self._check_revision(row, expected_revision)
            old = repo.revision(template_id, revision)
            if old is None:
                raise PlaybookError(
                    f"Revision {revision} of this template was not found.",
                    action="Refresh the history and choose another revision.",
                )
            content = TemplateDraft.from_content(old.content).validated()
            return self._save_content(repo, row, content, f"Restored revision {revision}")

    def duplicate(self, template_id: str) -> str:
        detail = self.get(template_id)
        if detail is None:
            raise PlaybookError(
                "This template no longer exists.", action="Refresh the list and try again."
            )
        draft = detail.draft()
        title = draft.title if draft.title.startswith(COPY_PREFIX) else COPY_PREFIX + draft.title
        return self.create(
            replace(draft, title=title), summary=f"Duplicated from “{detail.summary.title}”"
        )

    def set_favorite(self, template_id: str, favorite: bool) -> None:
        with self._database.session() as session:
            self._existing(PlaybookRepository(session), template_id).is_favorite = favorite

    def set_approved(self, template_id: str, approved: bool) -> None:
        with self._database.session() as session:
            self._existing(PlaybookRepository(session), template_id).is_approved = approved

    def set_archived(self, template_id: str, archived: bool) -> None:
        with self._database.session() as session:
            row = self._existing(PlaybookRepository(session), template_id)
            if archived and row.archived_at_utc is None:
                row.archived_at_utc = self._database.clock.now()
            elif not archived:
                row.archived_at_utc = None

    def add_outcome(self, template_id: str, outcome: Outcome, note: str | None = None) -> str:
        with self._database.session() as session:
            repo = PlaybookRepository(session)
            row = self._existing(repo, template_id)
            record = PlaybookOutcome(
                template_id=template_id,
                revision=row.revision,
                outcome=Outcome(outcome).value,
                note=(note or "").strip() or None,
                recorded_at_utc=self._database.clock.now(),
                author_actor_id=self._actor_id,
            )
            repo.add(record)
            return record.id

    def add_examples(self) -> int:
        """Add the example templates not added before; returns how many were added."""
        with self._database.session() as session:
            present = PlaybookRepository(session).example_keys()
        added = 0
        for example in EXAMPLES:
            if example.key not in present:
                self.create(example.draft, example_key=example.key, summary="Added from examples")
                added += 1
        return added

    def today(self) -> date:
        return to_local(self._database.clock.now()).date()

    def default_choices(self, detail: OrganizationDetail) -> tuple[str | None, str | None]:
        return default_choices(detail, today=self.today())

    def values_for(
        self,
        detail: OrganizationDetail | None,
        contact_id: str | None = None,
        game_id: str | None = None,
    ) -> Mapping[str, str | None]:
        return personalization_values(detail, contact_id, game_id, today=self.today())
