# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Playbook: outreach templates, revisions, outcomes, examples and personalized previews.

Placeholder filling, length limits and warnings are computed here (the same
domain rules the rest of the app uses); the browser only displays the result
and copies the text. tg_sales never sends messages.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ok, Svc
from tg_sales.api.routers.prospects import Created
from tg_sales.api.security import ConflictError, NotFoundError
from tg_sales.domain.playbook import (
    BODY_MAX,
    CHANNEL_LABELS,
    LINKEDIN_NOTE_LIMIT,
    OUTCOME_LABELS,
    PLACEHOLDER_LABELS,
    SUGGESTED_AUDIENCES,
    Channel,
    Outcome,
    TemplateDetail,
    TemplateDraft,
    TemplateFilters,
    TemplateSummary,
    length_warning,
    render,
    unresolved_warning,
)
from tg_sales.services.playbook import Vocabulary

router = APIRouter(tags=["playbook"])


class Choice(BaseModel):
    value: str
    label: str


class PlaybookMeta(BaseModel):
    channels: list[Choice]
    outcomes: list[Choice]
    placeholders: list[Choice]
    suggested_audiences: list[str]
    linkedin_note_limit: int
    body_max: int
    vocabulary: Vocabulary


class TemplateIn(Body):
    title: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=BODY_MAX)
    channel: Channel
    label: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=200)
    audience: str | None = Field(default=None, max_length=200)
    stage: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=10_000)
    tags: list[str] = Field(default_factory=list, max_length=30)
    expected_revision: int | None = None

    def draft(self) -> TemplateDraft:
        return TemplateDraft(
            title=self.title,
            body=self.body,
            channel=self.channel,
            label=self.label or None,
            category=self.category or None,
            audience=self.audience or None,
            stage=self.stage or None,
            notes=self.notes or None,
            tags=tuple(self.tags),
        )


class Flag(Body):
    value: bool


class RestoreIn(Body):
    revision: int = Field(ge=1)
    expected_revision: int | None = None


class OutcomeIn(Body):
    outcome: Outcome
    note: str | None = Field(default=None, max_length=2000)


class PreviewIn(Body):
    organization_id: str | None = None
    contact_id: str | None = None
    game_id: str | None = None


class PreviewView(BaseModel):
    text: str
    missing: list[str]
    unknown: list[str]
    complete: bool
    warning: str | None
    length_warning: str | None
    values: dict[str, str | None]
    default_contact_id: str | None
    default_game_id: str | None


@router.get("/playbook/meta", response_model=PlaybookMeta)
def meta(svc: Svc) -> PlaybookMeta:
    return PlaybookMeta(
        channels=[Choice(value=c.value, label=label) for c, label in CHANNEL_LABELS.items()],
        outcomes=[Choice(value=o.value, label=label) for o, label in OUTCOME_LABELS.items()],
        placeholders=[
            Choice(value=p.value, label=label) for p, label in PLACEHOLDER_LABELS.items()
        ],
        suggested_audiences=list(SUGGESTED_AUDIENCES),
        linkedin_note_limit=LINKEDIN_NOTE_LIMIT,
        body_max=BODY_MAX,
        vocabulary=svc.playbook.vocabulary(),
    )


@router.get("/playbook/templates", response_model=list[TemplateSummary])
def templates(
    svc: Svc,
    text: str = "",
    channel: Channel | None = None,
    audience: str | None = None,
    category: str | None = None,
    tag: str | None = None,
    favorites_only: bool = False,
    approved_only: bool = False,
    archived: bool = False,
) -> list[TemplateSummary]:
    return svc.playbook.templates(
        TemplateFilters(
            text=text,
            channel=channel,
            audience=audience or None,
            category=category or None,
            tag=tag or None,
            favorites_only=favorites_only,
            approved_only=approved_only,
            archived=archived,
        )
    )


@router.post("/playbook/templates", response_model=Created, status_code=201)
def create(body: TemplateIn, svc: Svc) -> Created:
    return Created(id=svc.playbook.create(body.draft()))


@router.get("/playbook/templates/{template_id}", response_model=TemplateDetail)
def get(template_id: str, svc: Svc) -> TemplateDetail:
    found = svc.playbook.get(template_id)
    if found is None:
        raise NotFoundError("That template")
    return found


@router.put("/playbook/templates/{template_id}", response_model=Ok)
def update(template_id: str, body: TemplateIn, svc: Svc) -> Ok:
    if not svc.playbook.update(template_id, body.draft(), expected_revision=body.expected_revision):
        raise ConflictError(
            "This template was changed elsewhere since you opened it.",
            action="Reload the template, then apply your changes again.",
        )
    return Ok()


@router.post("/playbook/templates/{template_id}/restore", response_model=Ok)
def restore(template_id: str, body: RestoreIn, svc: Svc) -> Ok:
    if not svc.playbook.restore_revision(
        template_id, body.revision, expected_revision=body.expected_revision
    ):
        raise ConflictError(
            "This template was changed elsewhere since you opened it.",
            action="Reload the template and choose the revision again.",
        )
    return Ok()


@router.post("/playbook/templates/{template_id}/duplicate", response_model=Created, status_code=201)
def duplicate(template_id: str, svc: Svc) -> Created:
    return Created(id=svc.playbook.duplicate(template_id))


@router.post("/playbook/templates/{template_id}/favorite", response_model=Ok)
def favorite(template_id: str, body: Flag, svc: Svc) -> Ok:
    svc.playbook.set_favorite(template_id, body.value)
    return Ok()


@router.post("/playbook/templates/{template_id}/approved", response_model=Ok)
def approved(template_id: str, body: Flag, svc: Svc) -> Ok:
    svc.playbook.set_approved(template_id, body.value)
    return Ok()


@router.post("/playbook/templates/{template_id}/archived", response_model=Ok)
def archived(template_id: str, body: Flag, svc: Svc) -> Ok:
    svc.playbook.set_archived(template_id, body.value)
    return Ok()


@router.post("/playbook/templates/{template_id}/outcomes", response_model=Created, status_code=201)
def add_outcome(template_id: str, body: OutcomeIn, svc: Svc) -> Created:
    return Created(id=svc.playbook.add_outcome(template_id, body.outcome, body.note or None))


@router.post("/playbook/examples", response_model=Ok)
def add_examples(svc: Svc) -> Ok:
    return Ok(count=svc.playbook.add_examples())


@router.post("/playbook/templates/{template_id}/preview", response_model=PreviewView)
def preview(template_id: str, body: PreviewIn, svc: Svc) -> PreviewView:
    template = svc.playbook.get(template_id)
    if template is None:
        raise NotFoundError("That template")
    detail = svc.prospects.get_detail(body.organization_id) if body.organization_id else None
    default_contact, default_game = (
        svc.playbook.default_choices(detail) if detail is not None else (None, None)
    )
    contact_id = body.contact_id or default_contact
    game_id = body.game_id or default_game
    values = dict(svc.playbook.values_for(detail, contact_id, game_id))
    rendered = render(template.summary.body, values)
    return PreviewView(
        text=rendered.text,
        missing=list(rendered.missing),
        unknown=list(rendered.unknown),
        complete=rendered.complete,
        warning=None if rendered.complete else unresolved_warning(rendered),
        length_warning=length_warning(template.summary.channel, rendered.text),
        values=values,
        default_contact_id=default_contact,
        default_game_id=default_game,
    )
