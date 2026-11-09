# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Game discovery: candidate games, timing windows and transparent lead scoring.

Everything here is grounded in data a source actually returned. Contact
details are never inferred: a candidate either has a business contact found
on a named public page (which still needs verification) or it has none.
Scores are sums of documented, configurable rules; there are no predictions.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from enum import StrEnum

from tg_sales.domain.enums import ReleasePrecision
from tg_sales.domain.normalization import domain_from_url, identifying_domain, normalize_email


class GameType(StrEnum):
    GAME = "game"
    DLC = "dlc"
    DEMO = "demo"
    OTHER = "other"


class Timing(StrEnum):
    UPCOMING = "upcoming"  # releases within the upcoming window
    RECENT = "recent"  # released within the recent window
    UNKNOWN_DATE = "unknown_date"  # "Coming soon" / "To be announced"
    OUTSIDE = "outside"  # dated, but outside both windows


TIMING_LABELS = {
    Timing.UPCOMING: "Upcoming",
    Timing.RECENT: "Recently released",
    Timing.UNKNOWN_DATE: "Date not announced",
    Timing.OUTSIDE: "Outside windows",
}


class ContactStatus(StrEnum):
    NOT_FOUND = "not_found"
    NEEDS_VERIFICATION = "needs_verification"
    VERIFIED_SOURCE = "verified_source"


CONTACT_STATUS_LABELS = {
    ContactStatus.NOT_FOUND: "Not found",
    ContactStatus.NEEDS_VERIFICATION: "Needs verification",
    ContactStatus.VERIFIED_SOURCE: "Verified source",
}


class LeadStatus(StrEnum):
    NEW = "new"
    SAVED = "saved"
    DISMISSED = "dismissed"


@dataclass(frozen=True)
class GameCandidate:
    """A game as reported by a source, normalized."""

    source: str
    external_id: str  # e.g. the Steam app id
    title: str
    store_url: str
    game_type: GameType
    release_date: date | None
    release_precision: ReleasePrecision
    release_text: str  # the source's original wording, e.g. "Coming soon"
    developers: tuple[str, ...]
    publishers: tuple[str, ...]
    genres: tuple[str, ...]
    categories: tuple[str, ...]
    platforms: tuple[str, ...]
    languages: tuple[str, ...]
    website: str | None
    support_email: str | None  # contact the developer published on the store page
    support_url: str | None
    parent_external_id: str | None  # base game of a DLC or demo
    parent_title: str | None
    fetched_at: datetime
    provenance_url: str  # where the details were read
    stale: bool = False  # served from cache because the source was unavailable

    @property
    def self_published(self) -> bool:
        """True when a developer is also listed as publisher (no separate publisher)."""
        devs = {d.casefold() for d in self.developers}
        return bool(devs) and all(p.casefold() in devs for p in self.publishers)

    @property
    def domain(self) -> str | None:
        return identifying_domain(domain_from_url(self.website))

    @property
    def primary_developer(self) -> str | None:
        return self.developers[0] if self.developers else None


@dataclass(frozen=True)
class DiscoveryWindow:
    upcoming_days: int = 90
    recent_days: int = 150

    def classify(self, candidate: GameCandidate, today: date) -> Timing:
        if (
            candidate.release_date is None
            or candidate.release_precision is ReleasePrecision.UNKNOWN
        ):
            return Timing.UNKNOWN_DATE
        released = candidate.release_date
        if candidate.release_precision is not ReleasePrecision.DAY:
            # Month/quarter/year precision: use the whole span it could fall in.
            end = _period_end(released, candidate.release_precision)
            if released <= today + timedelta(days=self.upcoming_days) and end >= today:
                return Timing.UPCOMING
            if end < today and end >= today - timedelta(days=self.recent_days):
                return Timing.RECENT
            return Timing.OUTSIDE
        if today <= released <= today + timedelta(days=self.upcoming_days):
            return Timing.UPCOMING
        if today - timedelta(days=self.recent_days) <= released < today:
            return Timing.RECENT
        return Timing.OUTSIDE


def _period_end(start: date, precision: ReleasePrecision) -> date:
    months = {ReleasePrecision.MONTH: 1, ReleasePrecision.QUARTER: 3, ReleasePrecision.YEAR: 12}
    index = start.year * 12 + start.month - 1 + months.get(precision, 0)
    first_after = date(index // 12, index % 12 + 1, 1)
    return first_after - timedelta(days=1)


def release_certainty(candidate: GameCandidate) -> str:
    return {
        ReleasePrecision.DAY: "Exact date",
        ReleasePrecision.MONTH: "Month only",
        ReleasePrecision.QUARTER: "Quarter only",
        ReleasePrecision.YEAR: "Year only",
        ReleasePrecision.UNKNOWN: "Not announced",
    }[candidate.release_precision]


@dataclass(frozen=True)
class ScoringRules:
    """Points per rule; all configurable and shown with every score."""

    upcoming: int = 30
    recent: int = 20
    unknown_date: int = 5
    self_published: int = 15
    has_website: int = 10
    business_contact: int = 15
    genre_match: int = 10  # per matching target genre, at most twice
    target_genres: tuple[str, ...] = ()
    dlc_penalty: int = -20


@dataclass(frozen=True)
class ScoreReason:
    points: int
    text: str


@dataclass(frozen=True)
class LeadScore:
    total: int
    reasons: tuple[ScoreReason, ...]
    confidence: str  # how complete the underlying data is: high / medium / low

    @property
    def explanation(self) -> str:
        return (
            "; ".join(f"{r.text} ({r.points:+d})" for r in self.reasons)
            or "No scoring rules matched"
        )


def score(
    candidate: GameCandidate,
    timing: Timing,
    rules: ScoringRules,
    contact_status: ContactStatus,
) -> LeadScore:
    reasons: list[ScoreReason] = []
    if timing is Timing.UPCOMING:
        reasons.append(ScoreReason(rules.upcoming, "Releases within the upcoming window"))
    elif timing is Timing.RECENT:
        reasons.append(ScoreReason(rules.recent, "Released within the recent window"))
    elif timing is Timing.UNKNOWN_DATE:
        reasons.append(ScoreReason(rules.unknown_date, "Release date not announced yet"))
    if candidate.self_published:
        reasons.append(
            ScoreReason(rules.self_published, "Self-published (no separate publisher listed)")
        )
    if candidate.website:
        reasons.append(ScoreReason(rules.has_website, "Official website listed"))
    if contact_status is not ContactStatus.NOT_FOUND:
        reasons.append(ScoreReason(rules.business_contact, "Public business contact found"))
    targets = {g.casefold() for g in rules.target_genres}
    matches = [g for g in candidate.genres if g.casefold() in targets][:2]
    for genre in matches:
        reasons.append(ScoreReason(rules.genre_match, f"Target genre: {genre}"))
    if candidate.game_type is GameType.DLC:
        reasons.append(ScoreReason(rules.dlc_penalty, "Downloadable content of another game"))
    total = max(0, min(100, sum(r.points for r in reasons)))
    known = sum(
        (
            candidate.release_precision is not ReleasePrecision.UNKNOWN,
            bool(candidate.developers),
            bool(candidate.genres),
            not candidate.stale,
        )
    )
    confidence = "high" if known == 4 else ("medium" if known >= 2 else "low")
    return LeadScore(total, tuple(reasons), confidence)


@dataclass(frozen=True)
class BusinessContact:
    email: str | None
    source_url: str | None
    source_label: str
    status: ContactStatus


def contact_from_store(candidate: GameCandidate) -> BusinessContact:
    """The contact the developer published on the store page, if any.

    It is a support address chosen by the developer, so it always needs
    verification before being treated as a business contact.
    """
    email = normalize_email(candidate.support_email)
    if email is None:
        return BusinessContact(None, None, "No public contact listed", ContactStatus.NOT_FOUND)
    return BusinessContact(
        email,
        candidate.provenance_url,
        "Support email listed on the store page",
        ContactStatus.NEEDS_VERIFICATION,
    )


@dataclass(frozen=True)
class DiscoveryFilters:
    timings: frozenset[Timing] = frozenset({Timing.UPCOMING, Timing.RECENT, Timing.UNKNOWN_DATE})
    platform: str | None = None  # "windows", "mac", "linux"
    self_published_only: bool = False
    language: str | None = None
    genre: str | None = None
    min_score: int = 0
    hide_in_crm: bool = False
    statuses: frozenset[LeadStatus] = frozenset({LeadStatus.NEW})
    include_dlc: bool = False


@dataclass(frozen=True)
class DiscoveryParams:
    window: DiscoveryWindow = DiscoveryWindow()
    max_candidates: int = 60
    rules: ScoringRules = ScoringRules()


@dataclass(frozen=True)
class SourceResult:
    """What a source returned for one run."""

    candidates: Sequence[GameCandidate]
    notes: Sequence[str] = field(default_factory=tuple)
    stale_count: int = 0
    failed_ids: Sequence[str] = field(default_factory=tuple)


class CrmState(StrEnum):
    NOT_IN_CRM = "not_in_crm"
    GAME_IN_CRM = "game_in_crm"  # this store game is already linked to a prospect
    STUDIO_IN_CRM = "studio_in_crm"  # same website domain as an existing prospect
    POSSIBLE_MATCH = "possible_match"  # same or similar studio name


CRM_STATE_LABELS = {
    CrmState.NOT_IN_CRM: "Not in CRM",
    CrmState.GAME_IN_CRM: "Game already in CRM",
    CrmState.STUDIO_IN_CRM: "Studio already in CRM",
    CrmState.POSSIBLE_MATCH: "Possible match",
}


@dataclass(frozen=True)
class LeadView:
    """A review-queue entry with everything the Discovery page shows."""

    id: str
    candidate: GameCandidate
    timing: Timing
    score: LeadScore
    contact: BusinessContact
    status: LeadStatus
    crm_state: CrmState
    crm_organization_id: str | None
    crm_organization_name: str | None
    last_checked: datetime
    outdated: bool  # not refreshed within the cache period, or served from cache
    organization_id: str | None  # prospect created from this lead


def matches_filters(view: LeadView, filters: DiscoveryFilters) -> bool:
    candidate = view.candidate
    if view.timing not in filters.timings or view.status not in filters.statuses:
        return False
    if candidate.game_type is GameType.DLC and not filters.include_dlc:
        return False
    if filters.platform and filters.platform not in candidate.platforms:
        return False
    if filters.self_published_only and not candidate.self_published:
        return False
    if filters.language and not any(
        filters.language.casefold() in lang.casefold() for lang in candidate.languages
    ):
        return False
    if filters.genre and filters.genre.casefold() not in {g.casefold() for g in candidate.genres}:
        return False
    if filters.hide_in_crm and view.crm_state in (CrmState.GAME_IN_CRM, CrmState.STUDIO_IN_CRM):
        return False
    return view.score.total >= filters.min_score
