"""Game discovery (Steam): runs, the review queue, contacts and saving to the CRM."""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from tg_sales.api.deps import Body, Ctx, JobRef, Ok, Svc, job_ref
from tg_sales.api.routers.prospects import Created
from tg_sales.domain.discovery import (
    DiscoveryFilters,
    DiscoveryParams,
    DiscoveryWindow,
    LeadStatus,
    LeadView,
    ScoringRules,
    Timing,
)
from tg_sales.domain.prospects import DuplicateCandidate
from tg_sales.services.discovery import RunInfo

router = APIRouter(tags=["discovery"])


class RulesIn(Body):
    upcoming: int = Field(default=30, ge=-100, le=100)
    recent: int = Field(default=20, ge=-100, le=100)
    unknown_date: int = Field(default=5, ge=-100, le=100)
    self_published: int = Field(default=15, ge=-100, le=100)
    has_website: int = Field(default=10, ge=-100, le=100)
    business_contact: int = Field(default=15, ge=-100, le=100)
    genre_match: int = Field(default=10, ge=-100, le=100)
    target_genres: list[str] = Field(default_factory=list, max_length=30)
    dlc_penalty: int = Field(default=-20, ge=-100, le=100)


class ParamsIn(Body):
    upcoming_days: int | None = Field(default=None, ge=1, le=365)
    recent_days: int | None = Field(default=None, ge=1, le=730)
    max_candidates: int = Field(default=60, ge=1, le=500)
    rules: RulesIn = Field(default_factory=RulesIn)


class FiltersIn(Body):
    timings: list[Timing] = Field(default_factory=lambda: [Timing.UPCOMING, Timing.RECENT])
    platform: str | None = None
    self_published_only: bool = False
    language: str | None = None
    genre: str | None = None
    min_score: int = Field(default=0, ge=-500, le=500)
    hide_in_crm: bool = False
    statuses: list[LeadStatus] = Field(default_factory=lambda: [LeadStatus.NEW])
    include_dlc: bool = False


class LeadQuery(Body):
    params: ParamsIn = Field(default_factory=ParamsIn)
    filters: FiltersIn = Field(default_factory=FiltersIn)


class LookupIn(Body):
    references: list[str] = Field(min_length=1, max_length=50)


class StatusIn(Body):
    status: LeadStatus


class LeadContactIn(Body):
    email: str = Field(min_length=3, max_length=320)
    source_url: str = Field(min_length=1, max_length=500)


class SaveIn(Body):
    existing_organization_id: str | None = None
    include_contact: bool = True


class DiscoveryMeta(BaseModel):
    sources: list[str]
    attribution: str
    upcoming_days: int
    recent_days: int
    rules: dict[str, object]
    timings: list[str]
    statuses: list[str]


def _params(
    ctx_settings_upcoming: int, ctx_settings_recent: int, body: ParamsIn
) -> DiscoveryParams:
    rules = body.rules
    return DiscoveryParams(
        window=DiscoveryWindow(
            body.upcoming_days or ctx_settings_upcoming, body.recent_days or ctx_settings_recent
        ),
        max_candidates=body.max_candidates,
        rules=ScoringRules(
            upcoming=rules.upcoming,
            recent=rules.recent,
            unknown_date=rules.unknown_date,
            self_published=rules.self_published,
            has_website=rules.has_website,
            business_contact=rules.business_contact,
            genre_match=rules.genre_match,
            target_genres=tuple(g.strip() for g in rules.target_genres if g.strip()),
            dlc_penalty=rules.dlc_penalty,
        ),
    )


@router.get("/discovery/meta", response_model=DiscoveryMeta)
def meta(svc: Svc) -> DiscoveryMeta:
    settings = svc.settings.get()
    source = svc.discovery.source("steam")
    defaults = ScoringRules()
    return DiscoveryMeta(
        sources=svc.discovery.source_names,
        attribution=getattr(source, "attribution", ""),
        upcoming_days=settings.discovery_upcoming_days,
        recent_days=settings.discovery_recent_days,
        rules={
            "upcoming": defaults.upcoming,
            "recent": defaults.recent,
            "unknown_date": defaults.unknown_date,
            "self_published": defaults.self_published,
            "has_website": defaults.has_website,
            "business_contact": defaults.business_contact,
            "genre_match": defaults.genre_match,
            "target_genres": list(defaults.target_genres),
            "dlc_penalty": defaults.dlc_penalty,
        },
        timings=[t.value for t in Timing],
        statuses=[s.value for s in LeadStatus],
    )


@router.post("/discovery/run", response_model=JobRef)
def run(body: ParamsIn, ctx: Ctx, svc: Svc) -> JobRef:
    settings = svc.settings.get()
    params = _params(settings.discovery_upcoming_days, settings.discovery_recent_days, body)
    return job_ref(
        ctx.jobs.submit(
            "discovery",
            lambda token, progress: svc.discovery.run(params, token=token, progress=progress),
            exclusive=True,
        )
    )


@router.post("/discovery/lookup", response_model=JobRef)
def lookup(body: LookupIn, ctx: Ctx, svc: Svc) -> JobRef:
    references = [r.strip() for r in body.references if r.strip()]
    return job_ref(
        ctx.jobs.submit(
            "discovery",
            lambda token, progress: svc.discovery.lookup(
                references, token=token, progress=progress
            ),
            exclusive=True,
        )
    )


@router.get("/discovery/last-run", response_model=RunInfo | None)
def last_run(svc: Svc) -> RunInfo | None:
    return svc.discovery.last_run()


@router.post("/discovery/leads/search", response_model=list[LeadView])
def leads(body: LeadQuery, svc: Svc) -> list[LeadView]:
    settings = svc.settings.get()
    params = _params(settings.discovery_upcoming_days, settings.discovery_recent_days, body.params)
    f = body.filters
    filters = DiscoveryFilters(
        timings=frozenset(f.timings),
        platform=f.platform or None,
        self_published_only=f.self_published_only,
        language=f.language or None,
        genre=f.genre or None,
        min_score=f.min_score,
        hide_in_crm=f.hide_in_crm,
        statuses=frozenset(f.statuses),
        include_dlc=f.include_dlc,
    )
    return svc.discovery.leads(params, filters)


@router.post("/discovery/leads/{lead_id}/status", response_model=Ok)
def set_status(lead_id: str, body: StatusIn, svc: Svc) -> Ok:
    svc.discovery.set_status(lead_id, body.status)
    return Ok()


@router.post("/discovery/leads/{lead_id}/find-contacts", response_model=JobRef)
def find_contacts(lead_id: str, ctx: Ctx, svc: Svc) -> JobRef:
    return job_ref(
        ctx.jobs.submit(
            "website-contacts",
            lambda token, _progress: svc.discovery.find_website_contacts(lead_id, token),
        )
    )


@router.post("/discovery/leads/{lead_id}/contact", response_model=Ok)
def set_contact(lead_id: str, body: LeadContactIn, svc: Svc) -> Ok:
    svc.discovery.set_contact(lead_id, body.email, body.source_url)
    return Ok()


@router.post("/discovery/leads/{lead_id}/verify-contact", response_model=Ok)
def verify_contact(lead_id: str, svc: Svc) -> Ok:
    svc.discovery.mark_contact_verified(lead_id)
    return Ok()


@router.get("/discovery/leads/{lead_id}/duplicates", response_model=list[DuplicateCandidate])
def duplicates(lead_id: str, svc: Svc) -> list[DuplicateCandidate]:
    return svc.discovery.duplicates_for(lead_id)


@router.post("/discovery/leads/{lead_id}/save", response_model=Created)
def save(lead_id: str, body: SaveIn, svc: Svc) -> Created:
    return Created(
        id=svc.discovery.save_to_prospects(
            lead_id,
            existing_organization_id=body.existing_organization_id,
            include_contact=body.include_contact,
        )
    )
