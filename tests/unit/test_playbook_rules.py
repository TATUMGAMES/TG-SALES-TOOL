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

from tg_sales.domain.enums import ReleasePrecision
from tg_sales.domain.playbook import (
    LINKEDIN_NOTE_LIMIT,
    Channel,
    PlaybookError,
    TemplateDraft,
    TemplateFilters,
    TemplateSummary,
    change_summary,
    length_warning,
    normalize_tags,
    placeholders_in,
    release_phrase,
    render,
    unknown_placeholders,
    unresolved_warning,
)
from tg_sales.domain.playbook_examples import EXAMPLES


def test_render_fills_known_values_and_reports_the_rest() -> None:
    text = "Hi {contact_name}, about {game_title} on {platform} ({studio_name}) {mystery}"
    result = render(text, {"contact_name": "Ana", "game_title": " Lantern Tides ", "platform": ""})
    assert result.text == "Hi Ana, about Lantern Tides on {platform} ({studio_name}) {mystery}"
    assert result.missing == ("platform", "studio_name")
    assert result.unknown == ("mystery",)
    assert not result.complete
    warning = unresolved_warning(result)
    assert "{platform} (platform)" in warning and "{studio_name} (studio name)" in warning
    assert "Not a known placeholder: {mystery}" in warning


def test_render_complete_and_ordinary_braces_untouched() -> None:
    result = render('Hi {contact_name}! JSON: {"a": 1} and { } {Upper}', {"contact_name": "Bo"})
    assert result.complete
    assert result.text == 'Hi Bo! JSON: {"a": 1} and { } {Upper}'


def test_render_repeated_placeholder_reported_once() -> None:
    result = render("{game_title} / {game_title}", {})
    assert result.missing == ("game_title",)
    assert placeholders_in("{b} {a} {b}") == ["b", "a"]
    assert unknown_placeholders("{studio_name} {nope}") == ["nope"]


def test_draft_validation_and_cleanup() -> None:
    draft = TemplateDraft(
        title="  Intro   email ",
        body="\nHello {contact_name}\n",
        label="  Short ",
        tags=("Launch", "launch", " ", "Data  buyer"),
    ).validated()
    assert draft.title == "Intro email"
    assert draft.body == "Hello {contact_name}"
    assert draft.label == "Short"
    assert draft.tags == ("Launch", "Data buyer")
    with pytest.raises(PlaybookError, match="title"):
        TemplateDraft(title=" ", body="x").validated()
    with pytest.raises(PlaybookError, match="message text"):
        TemplateDraft(title="t", body="  \n ").validated()
    with pytest.raises(PlaybookError, match="longer than"):
        TemplateDraft(title="t", body="x" * 20_001).validated()


def test_content_round_trip_and_change_summary() -> None:
    draft = TemplateDraft(title="A", body="B", channel=Channel.PHONE, tags=("x",))
    assert TemplateDraft.from_content(draft.content()) == draft
    assert TemplateDraft.from_content({"title": "A", "body": "B", "channel": "bogus"}).channel is (
        Channel.EMAIL
    )
    edited = TemplateDraft(title="A", body="C", channel=Channel.EMAIL, tags=("x",))
    assert change_summary(draft, edited) == "Changed message, channel"
    assert change_summary(draft, draft) == "No changes"


def test_linkedin_length_warning() -> None:
    assert length_warning(Channel.LINKEDIN_CONNECT, "x" * LINKEDIN_NOTE_LIMIT) is None
    warning = length_warning(Channel.LINKEDIN_CONNECT, "x" * (LINKEDIN_NOTE_LIMIT + 1))
    assert warning is not None and "301 characters" in warning
    assert length_warning(Channel.EMAIL, "x" * 5000) is None


def test_release_phrase() -> None:
    day = date(2027, 3, 14)
    assert release_phrase(day, ReleasePrecision.DAY) == "14 March 2027"
    assert release_phrase(day, ReleasePrecision.MONTH) == "March 2027"
    assert release_phrase(day, ReleasePrecision.QUARTER) == "Q1 2027"
    assert release_phrase(day, ReleasePrecision.YEAR) == "2027"
    assert release_phrase(day, ReleasePrecision.UNKNOWN) is None
    assert release_phrase(None, ReleasePrecision.DAY) is None


def summary(**overrides: object) -> TemplateSummary:
    from datetime import UTC, datetime

    values: dict[str, object] = {
        "id": "t1",
        "title": "Launch intro",
        "channel": Channel.EMAIL,
        "label": "Intro",
        "category": "Introduction",
        "audience": "Game studio",
        "stage": "Contacted",
        "tags": ("launch",),
        "is_favorite": False,
        "is_approved": True,
        "revision": 1,
        "updated_at": datetime(2026, 10, 1, tzinfo=UTC),
        "archived": False,
        "body": "Influencer network support",
    }
    values.update(overrides)
    return TemplateSummary(**values)  # type: ignore[arg-type]


def test_filters() -> None:
    s = summary()
    assert s.matches(TemplateFilters())
    assert s.matches(TemplateFilters(text="influencer LAUNCH"))
    assert not s.matches(TemplateFilters(text="publisher"))
    assert s.matches(TemplateFilters(channel=Channel.EMAIL, audience="game STUDIO", tag="Launch"))
    assert not s.matches(TemplateFilters(channel=Channel.PHONE))
    assert not s.matches(TemplateFilters(favorites_only=True))
    assert not summary(is_approved=False).matches(TemplateFilters(approved_only=True))
    assert not s.matches(TemplateFilters(archived=True))
    assert summary(archived=True).matches(TemplateFilters(archived=True))


def test_examples_are_valid_and_careful() -> None:
    keys = [e.key for e in EXAMPLES]
    assert len(keys) == len(set(keys))
    for example in EXAMPLES:
        draft = example.draft.validated()
        assert unknown_placeholders(draft.body) == [], example.key
        assert "@" not in draft.body  # no addresses in shipped examples
        text = f"{draft.body} {draft.notes or ''}".lower()
        if any(ch.isdigit() for ch in draft.body.replace("{", "")):
            assert "approv" in text, f"{example.key}: figures need an approval note"
        if draft.channel is Channel.LINKEDIN_CONNECT:
            assert len(draft.body) < LINKEDIN_NOTE_LIMIT - 60  # room for filled values
    la = next(e for e in EXAMPLES if e.key.startswith("la-studio"))
    assert "subject to approval" in la.draft.body and "may be available" in la.draft.body
    assert "guarantee" in (la.draft.notes or "")


def test_normalize_tags_limits_length() -> None:
    assert normalize_tags(["x" * 100]) == ("x" * 40,)
