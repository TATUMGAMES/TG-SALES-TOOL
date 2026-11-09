# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

from __future__ import annotations

from datetime import date

import pytest

from tg_sales.db.database import Database
from tg_sales.domain.enums import ReleasePrecision
from tg_sales.domain.playbook import (
    Channel,
    Outcome,
    PlaybookError,
    TemplateDraft,
    TemplateFilters,
)
from tg_sales.domain.playbook_examples import EXAMPLES
from tg_sales.domain.prospects import ContactDraft, GameDraft, OrganizationDraft
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.playbook import PlaybookService, personalization_values
from tg_sales.services.prospects import ProspectService

pytestmark = pytest.mark.integration

DRAFT = TemplateDraft(
    title="Launch intro",
    body="Hi {contact_name}, congratulations on {game_title}.",
    channel=Channel.EMAIL,
    audience="Game studio",
    category="Introduction",
    tags=("launch",),
)


@pytest.fixture
def service(database: Database) -> PlaybookService:
    return PlaybookService(database, ensure_local_actor(database))


def test_create_edit_history_and_restore(service: PlaybookService) -> None:
    template_id = service.create(DRAFT)
    detail = service.get(template_id)
    assert detail is not None
    assert detail.summary.revision == 1 and not detail.summary.is_approved
    assert detail.author and [r.summary for r in detail.revisions] == ["Created"]

    assert not service.update(template_id, DRAFT, expected_revision=1)  # no change
    edited = TemplateDraft(
        **{**DRAFT.content(), "channel": Channel.FOLLOW_UP, "tags": ("launch", "q4")}
    )  # type: ignore[arg-type]
    assert service.update(template_id, edited, expected_revision=1)
    detail = service.get(template_id)
    assert detail is not None and detail.summary.revision == 2
    assert detail.revisions[0].summary == "Changed channel, tags"
    assert detail.summary.channel is Channel.FOLLOW_UP

    with pytest.raises(PlaybookError, match="changed since you opened it"):
        service.update(template_id, DRAFT, expected_revision=1)

    assert service.restore_revision(template_id, 1, expected_revision=2)
    detail = service.get(template_id)
    assert detail is not None and detail.summary.revision == 3
    assert detail.revisions[0].summary == "Restored revision 1"
    assert detail.draft().content() == DRAFT.validated().content()
    assert [r.revision for r in detail.revisions] == [3, 2, 1]
    with pytest.raises(PlaybookError, match="Revision 9"):
        service.restore_revision(template_id, 9)


def test_editing_text_removes_approval(service: PlaybookService) -> None:
    template_id = service.create(DRAFT)
    service.set_approved(template_id, True)
    retagged = TemplateDraft(**{**DRAFT.content(), "channel": Channel.EMAIL, "tags": ("x",)})  # type: ignore[arg-type]
    service.update(template_id, retagged)
    detail = service.get(template_id)
    assert detail is not None and detail.summary.is_approved  # tags only: still approved
    reworded = TemplateDraft(**{**retagged.content(), "channel": Channel.EMAIL, "body": "Hello"})  # type: ignore[arg-type]
    service.update(template_id, reworded)
    detail = service.get(template_id)
    assert detail is not None and not detail.summary.is_approved
    assert "approval removed" in detail.revisions[0].summary


def test_list_filters_favorites_archive_duplicate(service: PlaybookService) -> None:
    a = service.create(DRAFT)
    b = service.create(TemplateDraft(title="Publisher note", body="Hi", channel=Channel.PUBLISHER))
    service.set_favorite(b, True)
    assert [t.id for t in service.templates()] == [b, a]  # favorites first
    assert [t.id for t in service.templates(TemplateFilters(channel=Channel.PUBLISHER))] == [b]
    assert [t.id for t in service.templates(TemplateFilters(text="congratulations"))] == [a]

    copy = service.duplicate(a)
    copied = service.get(copy)
    assert copied is not None and copied.summary.title == "Copy of Launch intro"
    assert not copied.summary.is_favorite and not copied.summary.is_approved
    assert copied.revisions[0].summary == "Duplicated from “Launch intro”"

    service.set_archived(a, True)
    assert a not in [t.id for t in service.templates()]
    assert [t.id for t in service.templates(TemplateFilters(archived=True))] == [a]
    assert service.count() == 2 and service.count(include_archived=True) == 3
    service.set_archived(a, False)
    assert a in [t.id for t in service.templates()]

    vocab = service.vocabulary()
    assert vocab.audiences == ("Game studio",) and vocab.tags == ("launch",)
    with pytest.raises(PlaybookError, match="no longer exists"):
        service.set_favorite("missing", True)


def test_outcome_notes(service: PlaybookService) -> None:
    template_id = service.create(DRAFT)
    service.add_outcome(template_id, Outcome.REPLY, "  Asked for deck ")
    service.add_outcome(template_id, Outcome.NO_REPLY)
    detail = service.get(template_id)
    assert detail is not None
    assert [o.outcome for o in detail.outcomes] == [Outcome.NO_REPLY, Outcome.REPLY]
    assert detail.outcomes[1].note == "Asked for deck" and detail.outcomes[0].note is None


def test_examples_added_once(service: PlaybookService) -> None:
    assert service.add_examples() == len(EXAMPLES)
    assert service.add_examples() == 0
    templates = service.templates()
    assert len(templates) == len(EXAMPLES)
    assert not any(t.is_approved for t in templates)
    # Archived examples still count as added.
    service.set_archived(templates[0].id, True)
    assert service.add_examples() == 0


def test_personalization_from_prospect(database: Database, service: PlaybookService) -> None:
    prospects = ProspectService(database, ensure_local_actor(database))
    org = prospects.create(
        OrganizationDraft("Harbor Light Studio"),
        [ContactDraft(name=None, email="info@harborlight.example"), ContactDraft(name="Ana Ruiz")],
    )
    prospects.add_game(
        org,
        GameDraft(
            "Old Game",
            platform="PC",
            release_date=date(2025, 1, 5),
            release_precision=ReleasePrecision.DAY,
        ),
    )
    prospects.add_game(
        org,
        GameDraft(
            "Lantern Tides",
            platform="PC, Mac",
            release_date=date(2026, 11, 1),
            release_precision=ReleasePrecision.MONTH,
        ),
    )
    detail = prospects.get_detail(org)
    values = service.values_for(detail)
    assert values == {
        "studio_name": "Harbor Light Studio",
        "contact_name": "Ana Ruiz",
        "game_title": "Lantern Tides",
        "platform": "PC, Mac",
        "release_date": "November 2026",
    }
    old = next(g for g in detail.games if g.title == "Old Game")  # type: ignore[union-attr]
    assert service.values_for(detail, game_id=old.id)["release_date"] == "5 January 2025"
    # After every release date has passed, the most recent game is used.
    later = personalization_values(detail, today=date(2030, 1, 1))
    assert later["game_title"] == "Lantern Tides"
    assert personalization_values(None, today=date(2026, 1, 1))["studio_name"] is None
