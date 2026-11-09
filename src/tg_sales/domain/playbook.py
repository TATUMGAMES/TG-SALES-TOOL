# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Outreach message templates: channels, placeholders and personalization.

Templates are text with placeholders such as ``{studio_name}``. Rendering
replaces the placeholders it has values for and reports the rest, so the UI
can warn before anything with a raw placeholder is copied. tg_sales never
sends messages; users copy the text into their own email or LinkedIn.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from enum import StrEnum

from tg_sales.domain.enums import ReleasePrecision
from tg_sales.errors import ConflictError, TgSalesError


class PlaybookError(TgSalesError):
    """A template could not be saved or changed."""


class StaleRevisionError(PlaybookError, ConflictError):
    """The template was saved by someone else after it was opened."""


class Channel(StrEnum):
    EMAIL = "email"
    LINKEDIN_CONNECT = "linkedin_connect"
    LINKEDIN_MESSAGE = "linkedin_message"
    PHONE = "phone"
    FOLLOW_UP = "follow_up"
    PUBLISHER = "publisher"
    DATA_BUYER = "data_buyer"


CHANNEL_LABELS: dict[Channel, str] = {
    Channel.EMAIL: "Email",
    Channel.LINKEDIN_CONNECT: "LinkedIn connection note",
    Channel.LINKEDIN_MESSAGE: "LinkedIn message",
    Channel.PHONE: "Phone script",
    Channel.FOLLOW_UP: "Follow-up",
    Channel.PUBLISHER: "Publisher outreach",
    Channel.DATA_BUYER: "Data buyer outreach",
}

# LinkedIn limits connection notes (300 characters at the time of writing;
# some accounts get fewer). Shown as a warning, never enforced.
LINKEDIN_NOTE_LIMIT = 300

SUGGESTED_AUDIENCES: tuple[str, ...] = (
    "Game studio",
    "Los Angeles studio",
    "Publisher",
    "Data buyer",
)


class Placeholder(StrEnum):
    STUDIO_NAME = "studio_name"
    GAME_TITLE = "game_title"
    CONTACT_NAME = "contact_name"
    RELEASE_DATE = "release_date"
    PLATFORM = "platform"


PLACEHOLDER_LABELS: dict[Placeholder, str] = {
    Placeholder.STUDIO_NAME: "Studio name",
    Placeholder.GAME_TITLE: "Game title",
    Placeholder.CONTACT_NAME: "Contact name",
    Placeholder.RELEASE_DATE: "Release date",
    Placeholder.PLATFORM: "Platform",
}

# ``{name}`` with a lower-case identifier. Other braces are left alone, so
# ordinary text such as "{ }" or JSON snippets is not mistaken for a placeholder.
PLACEHOLDER_PATTERN = re.compile(r"\{([a-z][a-z0-9_]*)\}")

TITLE_MAX = 200
BODY_MAX = 20_000
FIELD_MAX = 120
TAG_MAX = 40


class Outcome(StrEnum):
    """What happened after a message was used (recorded manually)."""

    REPLY = "reply"
    MEETING = "meeting"
    NO_REPLY = "no_reply"
    NOT_INTERESTED = "not_interested"
    OTHER = "other"


OUTCOME_LABELS: dict[Outcome, str] = {
    Outcome.REPLY: "Got a reply",
    Outcome.MEETING: "Led to a meeting",
    Outcome.NO_REPLY: "No reply",
    Outcome.NOT_INTERESTED: "Not interested",
    Outcome.OTHER: "Other",
}


def placeholders_in(text: str) -> list[str]:
    """Placeholder names used in ``text``, in order of first appearance."""
    seen: dict[str, None] = {}
    for match in PLACEHOLDER_PATTERN.finditer(text):
        seen.setdefault(match.group(1), None)
    return list(seen)


def unknown_placeholders(text: str) -> list[str]:
    known = {p.value for p in Placeholder}
    return [name for name in placeholders_in(text) if name not in known]


@dataclass(frozen=True, slots=True)
class Rendered:
    text: str
    missing: tuple[str, ...]  # known placeholders without a value
    unknown: tuple[str, ...]  # placeholders tg_sales does not know

    @property
    def unresolved(self) -> tuple[str, ...]:
        return (*self.missing, *self.unknown)

    @property
    def complete(self) -> bool:
        return not self.unresolved


def render(text: str, values: Mapping[str, str | None]) -> Rendered:
    """Fill the placeholders that have a non-blank value; leave the rest as written."""
    known = {p.value for p in Placeholder}
    missing: dict[str, None] = {}
    unknown: dict[str, None] = {}

    def replace(match: re.Match[str]) -> str:
        name = match.group(1)
        value = (values.get(name) or "").strip()
        if value:
            return value
        (missing if name in known else unknown).setdefault(name, None)
        return match.group(0)

    filled = PLACEHOLDER_PATTERN.sub(replace, text)
    return Rendered(filled, tuple(missing), tuple(unknown))


def unresolved_warning(rendered: Rendered) -> str:
    """Plain-language warning for placeholders that are still in the text."""
    parts = []
    if rendered.missing:
        names = ", ".join(
            f"{{{n}}} ({PLACEHOLDER_LABELS[Placeholder(n)].lower()})" for n in rendered.missing
        )
        parts.append(f"No value for {names}.")
    if rendered.unknown:
        names = ", ".join(f"{{{n}}}" for n in rendered.unknown)
        parts.append(f"Not a known placeholder: {names}.")
    return " ".join(parts)


def release_phrase(value: date | None, precision: ReleasePrecision) -> str | None:
    """A release date as it would be written in a message ("14 March 2027", "Q3 2027")."""
    if value is None or precision is ReleasePrecision.UNKNOWN:
        return None
    if precision is ReleasePrecision.YEAR:
        return str(value.year)
    if precision is ReleasePrecision.QUARTER:
        return f"Q{(value.month - 1) // 3 + 1} {value.year}"
    if precision is ReleasePrecision.MONTH:
        return value.strftime("%B %Y")
    return f"{value.day} {value.strftime('%B %Y')}"


def normalize_tags(tags: Sequence[str]) -> tuple[str, ...]:
    """Trim, drop blanks and case-insensitive duplicates, keep the first spelling."""
    result: dict[str, str] = {}
    for tag in tags:
        clean = " ".join(tag.split())
        if clean:
            result.setdefault(clean.casefold(), clean[:TAG_MAX])
    return tuple(result.values())


def _clean(value: str | None, limit: int = FIELD_MAX) -> str | None:
    text = " ".join((value or "").split())
    return text[:limit] or None


@dataclass(frozen=True, slots=True)
class TemplateDraft:
    title: str
    body: str
    channel: Channel = Channel.EMAIL
    label: str | None = None
    category: str | None = None
    audience: str | None = None
    stage: str | None = None
    notes: str | None = None
    tags: tuple[str, ...] = ()

    def validated(self) -> TemplateDraft:
        title = _clean(self.title, TITLE_MAX)
        if not title:
            raise PlaybookError("A template needs a title.", action="Enter a short title.")
        body = self.body.strip("\n")
        if not body.strip():
            raise PlaybookError("A template needs message text.", action="Enter the message.")
        if len(body) > BODY_MAX:
            raise PlaybookError(
                f"The message is longer than {BODY_MAX:,} characters.",
                action="Shorten the message or split it into several templates.",
            )
        return TemplateDraft(
            title=title,
            body=body,
            channel=Channel(self.channel),
            label=_clean(self.label),
            category=_clean(self.category),
            audience=_clean(self.audience),
            stage=_clean(self.stage),
            notes=(self.notes or "").strip() or None,
            tags=normalize_tags(self.tags),
        )

    def content(self) -> dict[str, object]:
        """The editable fields, as stored in a revision."""
        return {
            "title": self.title,
            "body": self.body,
            "channel": self.channel.value,
            "label": self.label,
            "category": self.category,
            "audience": self.audience,
            "stage": self.stage,
            "notes": self.notes,
            "tags": list(self.tags),
        }

    @classmethod
    def from_content(cls, data: Mapping[str, object]) -> TemplateDraft:
        def text(key: str) -> str | None:
            value = data.get(key)
            return value if isinstance(value, str) else None

        try:
            channel = Channel(str(data.get("channel") or Channel.EMAIL.value))
        except ValueError:
            channel = Channel.EMAIL
        tags = data.get("tags")
        return cls(
            title=text("title") or "",
            body=text("body") or "",
            channel=channel,
            label=text("label"),
            category=text("category"),
            audience=text("audience"),
            stage=text("stage"),
            notes=text("notes"),
            tags=tuple(str(t) for t in tags) if isinstance(tags, list) else (),
        )


def length_warning(channel: Channel, text: str) -> str | None:
    if channel is Channel.LINKEDIN_CONNECT and len(text) > LINKEDIN_NOTE_LIMIT:
        return (
            f"{len(text)} characters: LinkedIn connection notes are limited to about "
            f"{LINKEDIN_NOTE_LIMIT} characters (fewer for some accounts)."
        )
    return None


@dataclass(frozen=True, slots=True)
class TemplateFilters:
    text: str = ""
    channel: Channel | None = None
    audience: str | None = None
    category: str | None = None
    tag: str | None = None
    favorites_only: bool = False
    approved_only: bool = False
    archived: bool = False  # show archived templates instead of active ones


@dataclass(frozen=True, slots=True)
class TemplateSummary:
    id: str
    title: str
    channel: Channel
    label: str | None
    category: str | None
    audience: str | None
    stage: str | None
    tags: tuple[str, ...]
    is_favorite: bool
    is_approved: bool
    revision: int
    updated_at: datetime
    archived: bool
    body: str

    def matches(self, filters: TemplateFilters) -> bool:
        if filters.archived != self.archived:
            return False
        if filters.channel is not None and self.channel is not filters.channel:
            return False
        for wanted, actual in (
            (filters.audience, self.audience),
            (filters.category, self.category),
        ):
            if wanted and (actual or "").casefold() != wanted.casefold():
                return False
        if filters.tag and filters.tag.casefold() not in {t.casefold() for t in self.tags}:
            return False
        if filters.favorites_only and not self.is_favorite:
            return False
        if filters.approved_only and not self.is_approved:
            return False
        words = filters.text.casefold().split()
        if words:
            haystack = " ".join(
                [
                    self.title,
                    self.body,
                    self.label or "",
                    self.category or "",
                    self.audience or "",
                    self.stage or "",
                    CHANNEL_LABELS[self.channel],
                    *self.tags,
                ]
            ).casefold()
            return all(word in haystack for word in words)
        return True


@dataclass(frozen=True, slots=True)
class RevisionInfo:
    revision: int
    created_at: datetime
    author: str | None
    summary: str
    content: TemplateDraft


@dataclass(frozen=True, slots=True)
class OutcomeNote:
    id: str
    outcome: Outcome
    note: str | None
    recorded_at: datetime
    author: str | None


@dataclass(frozen=True, slots=True)
class TemplateDetail:
    summary: TemplateSummary
    notes: str | None
    author: str | None
    created_at: datetime
    revisions: tuple[RevisionInfo, ...]  # newest first
    outcomes: tuple[OutcomeNote, ...] = field(default=())  # newest first
    example_key: str | None = None

    @property
    def id(self) -> str:
        return self.summary.id

    def draft(self) -> TemplateDraft:
        s = self.summary
        return TemplateDraft(
            title=s.title,
            body=s.body,
            channel=s.channel,
            label=s.label,
            category=s.category,
            audience=s.audience,
            stage=s.stage,
            notes=self.notes,
            tags=s.tags,
        )


def change_summary(old: TemplateDraft, new: TemplateDraft) -> str:
    """Short description of what an edit changed, for the revision history."""
    names = {
        "title": "title",
        "body": "message",
        "channel": "channel",
        "label": "label",
        "category": "category",
        "audience": "audience",
        "stage": "stage",
        "notes": "notes",
        "tags": "tags",
    }
    before, after = old.content(), new.content()
    changed = [label for key, label in names.items() if before[key] != after[key]]
    return "Changed " + ", ".join(changed) if changed else "No changes"
