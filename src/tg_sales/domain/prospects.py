# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Prospect (organization) data passed between services and the UI, and duplicate rules.

Duplicate detection distinguishes strong evidence (same identifying website
domain or same contact email) from weak evidence (same or very similar name).
Similarly named studios are legitimate, so name matches are only ever
suggestions for the user to confirm; nothing is merged automatically on a name.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from difflib import SequenceMatcher
from enum import StrEnum

from tg_sales.domain.enums import (
    ActivityType,
    ContactStatus,
    GameRole,
    OrganizationType,
    RecordSource,
    ReleasePrecision,
)
from tg_sales.domain.normalization import core_name, identifying_domain, normalize_name

SIMILAR_NAME_THRESHOLD = 0.88


@dataclass(frozen=True)
class OrganizationDraft:
    """Values entered for a new or edited organization.

    ``custom_fields`` holds changes by field key (None clears a value); fields
    not mentioned keep their values. Names in ``keep`` (``reviewed_on``,
    ``qualification_source_url``) were not sent by the form and keep their
    current values, so an older or simpler form never erases them.
    """

    name: str
    website: str | None = None
    company_type: OrganizationType = OrganizationType.UNKNOWN
    location: str | None = None
    country: str | None = None
    tags: tuple[str, ...] = ()
    notes: str | None = None
    reviewed_on: date | None = None
    qualification_source_url: str | None = None
    custom_fields: Mapping[str, object] = field(default_factory=dict)
    keep: frozenset[str] = frozenset()


@dataclass(frozen=True)
class ContactDraft:
    name: str | None = None
    role_title: str | None = None
    email: str | None = None
    social_urls: Mapping[str, str] = field(default_factory=dict)
    status: ContactStatus = ContactStatus.UNKNOWN
    notes: str | None = None
    provenance: str | None = None
    source_url: str | None = None
    custom_fields: Mapping[str, object] = field(default_factory=dict)  # changes by key
    keep: frozenset[str] = frozenset()  # fields the form did not send (kept as they are)


@dataclass(frozen=True)
class GameDraft:
    title: str
    role: GameRole = GameRole.DEVELOPER
    platform: str | None = None
    store_url: str | None = None
    release_date: date | None = None
    release_precision: ReleasePrecision = ReleasePrecision.UNKNOWN


@dataclass(frozen=True)
class ProspectQuery:
    text: str = ""
    tag: str | None = None
    company_type: OrganizationType | None = None
    include_archived: bool = False
    limit: int = 500
    offset: int = 0


@dataclass(frozen=True)
class OrganizationSummary:
    id: str
    name: str
    domain: str | None
    website: str | None
    company_type: OrganizationType
    location: str | None
    country: str | None
    tags: tuple[str, ...]
    contact_count: int
    game_count: int
    open_opportunity_count: int
    next_follow_up: datetime | None
    updated_at: datetime
    archived: bool


@dataclass(frozen=True)
class SearchResult:
    rows: tuple[OrganizationSummary, ...]
    total: int  # matches before the display limit

    @property
    def truncated(self) -> bool:
        return self.total > len(self.rows)


@dataclass(frozen=True)
class ContactInfo:
    id: str
    name: str | None
    role_title: str | None
    email: str | None
    social_urls: Mapping[str, str]
    status: ContactStatus
    notes: str | None
    provenance: str | None
    source_url: str | None
    source: RecordSource
    archived: bool
    custom_fields: Mapping[str, object] = field(default_factory=dict)


@dataclass(frozen=True)
class CustomValue:
    """A custom field of a record with its value (None when empty)."""

    key: str
    label: str
    field_type: str
    value: object | None


@dataclass(frozen=True)
class GameInfo:
    id: str
    title: str
    role: GameRole
    platform: str | None
    store_url: str | None
    release_date: date | None
    release_precision: ReleasePrecision


@dataclass(frozen=True)
class OpportunityInfo:
    id: str
    title: str | None
    product_lane: str  # sales lane key
    stage_name: str
    next_action_at: datetime | None
    next_action_note: str | None
    closed: bool


@dataclass(frozen=True)
class TimelineEntry:
    id: str
    type: ActivityType
    occurred_at: datetime
    summary: str
    voided: bool = False


@dataclass(frozen=True)
class LinkInfo:
    label: str
    url: str


@dataclass(frozen=True)
class OrganizationDetail:
    id: str
    name: str
    website: str | None
    domain: str | None
    company_type: OrganizationType
    location: str | None
    country: str | None
    tags: tuple[str, ...]
    notes: str | None
    source: RecordSource
    source_detail: str | None
    created_at: datetime
    updated_at: datetime
    archived: bool
    contacts: tuple[ContactInfo, ...]
    games: tuple[GameInfo, ...]
    opportunities: tuple[OpportunityInfo, ...]
    timeline: tuple[TimelineEntry, ...]
    links: tuple[LinkInfo, ...]
    reviewed_on: date | None = None
    qualification_source_url: str | None = None
    custom_fields: tuple[CustomValue, ...] = ()  # active prospect fields, in order
    contact_fields: tuple[CustomValue, ...] = ()  # active contact field definitions

    @property
    def follow_ups(self) -> tuple[OpportunityInfo, ...]:
        pending = [
            (o.next_action_at, o.id, o)
            for o in self.opportunities
            if o.next_action_at is not None and not o.closed
        ]
        return tuple(o for _, _, o in sorted(pending, key=lambda item: (item[0], item[1])))


class MatchStrength(StrEnum):
    STRONG = "strong"  # same identifying domain or contact email
    NAME = "name"  # same name (ignoring case, punctuation and company form)
    SIMILAR = "similar"  # similar name


@dataclass(frozen=True)
class OrganizationKey:
    """The fields of an existing organization used for duplicate detection."""

    id: str
    name: str
    domain: str | None
    archived: bool = False


@dataclass(frozen=True)
class DuplicateCandidate:
    id: str
    name: str
    domain: str | None
    strength: MatchStrength
    reason: str
    archived: bool = False


def name_similarity(a: str, b: str) -> float:
    left, right = core_name(a), core_name(b)
    if not left or not right:
        return 0.0
    return SequenceMatcher(None, left, right).ratio()


# Words so common in studio names that sharing them says nothing about similarity.
COMMON_NAME_WORDS = frozenset(
    {
        "game",
        "games",
        "gaming",
        "studio",
        "studios",
        "interactive",
        "entertainment",
        "digital",
        "software",
        "productions",
        "production",
        "labs",
        "lab",
        "media",
        "works",
        "team",
        "publishing",
        "the",
        "and",
        "of",
    }
)
# Distinctive words shared by more organizations than this are not used to find
# similar names (it would compare against too many records to be useful or fast).
MAX_BLOCK_SIZE = 300


def significant_words(name: str) -> list[str]:
    """Distinctive words of a name, used to find similarly named organizations."""
    words = [w for w in core_name(name).split() if w not in COMMON_NAME_WORDS]
    return list(dict.fromkeys(words))


class OrganizationIndex:
    """In-memory lookup of existing organizations by domain, name and distinctive words.

    Similar names are only compared among organizations that share a distinctive
    word, which keeps lookups fast with very large prospect lists.
    """

    def __init__(self, keys: Iterable[OrganizationKey] = ()) -> None:
        self._by_id: dict[str, OrganizationKey] = {}
        self._by_domain: dict[str, list[str]] = {}
        self._by_name: dict[str, list[str]] = {}
        self._by_block: dict[str, list[str]] = {}
        self._by_words: dict[str, list[str]] = {}
        for key in keys:
            self.add(key)

    def add(self, key: OrganizationKey) -> None:
        self._by_id[key.id] = key
        domain = identifying_domain(key.domain)
        if domain:
            self._by_domain.setdefault(domain, []).append(key.id)
        self._by_name.setdefault(core_name(key.name) or normalize_name(key.name), []).append(key.id)
        for word in significant_words(key.name):
            self._by_block.setdefault(word, []).append(key.id)
        words = " ".join(sorted(significant_words(key.name)))
        if words:
            self._by_words.setdefault(words, []).append(key.id)

    def get(self, organization_id: str) -> OrganizationKey | None:
        return self._by_id.get(organization_id)

    def find(
        self,
        name: str,
        domain: str | None = None,
        *,
        email_matches: Mapping[str, str] | None = None,
        exclude_id: str | None = None,
    ) -> list[DuplicateCandidate]:
        """Existing organizations that may be the same as ``name``/``domain``.

        ``email_matches`` maps organization ids to a contact email they share
        with the new record. Results are ordered strongest first.
        """
        found: dict[str, DuplicateCandidate] = {}

        def add(org_id: str, strength: MatchStrength, reason: str) -> None:
            if org_id == exclude_id or org_id in found:
                return
            key = self._by_id[org_id]
            found[org_id] = DuplicateCandidate(
                key.id, key.name, key.domain, strength, reason, key.archived
            )

        own_domain = identifying_domain(domain)
        if own_domain:
            for org_id in self._by_domain.get(own_domain, []):
                add(org_id, MatchStrength.STRONG, f"Same website domain ({own_domain})")
        for org_id, email in (email_matches or {}).items():
            if org_id in self._by_id:
                add(org_id, MatchStrength.STRONG, f"Has a contact with the same email ({email})")
        name_key = core_name(name) or normalize_name(name)
        for org_id in self._by_name.get(name_key, []):
            add(org_id, MatchStrength.NAME, "Same name")
        words = " ".join(sorted(significant_words(name)))
        for org_id in self._by_words.get(words, []) if words else []:
            add(org_id, MatchStrength.SIMILAR, "Same name apart from words like Games or Studio")
        compared: set[str] = set()
        for word in significant_words(name):
            block = self._by_block.get(word, [])
            if len(block) > MAX_BLOCK_SIZE:
                continue
            for org_id in block:
                if org_id in found or org_id in compared:
                    continue
                compared.add(org_id)
                if name_similarity(name, self._by_id[org_id].name) >= SIMILAR_NAME_THRESHOLD:
                    add(org_id, MatchStrength.SIMILAR, "Similar name")
        order = {MatchStrength.STRONG: 0, MatchStrength.NAME: 1, MatchStrength.SIMILAR: 2}
        return sorted(found.values(), key=lambda c: (order[c.strength], c.name.casefold(), c.id))


def name_conflicts_with_domain(candidate: DuplicateCandidate, domain: str | None) -> bool:
    """True when names match but both records have different identifying domains.

    That is the typical sign of two different studios with similar names.
    """
    own = identifying_domain(domain)
    theirs = identifying_domain(candidate.domain)
    return bool(own and theirs and own != theirs)


def merge_tags(existing: Sequence[str], new: Iterable[str]) -> tuple[str, ...]:
    """Union of tags, keeping existing order and ignoring case-only duplicates."""
    result = list(existing)
    seen = {t.casefold() for t in result}
    for tag in new:
        cleaned = tag.strip()
        if cleaned and cleaned.casefold() not in seen:
            result.append(cleaned)
            seen.add(cleaned.casefold())
    return tuple(result)
