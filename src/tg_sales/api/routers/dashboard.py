"""Dashboard KPIs for a period, with salesperson and product-lane filters."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter
from pydantic import BaseModel

from tg_sales.api.deps import Svc
from tg_sales.domain.enums import ProductLane
from tg_sales.domain.kpi import KpiFilters
from tg_sales.domain.periods import (
    PRESET_LABELS,
    DateRange,
    PeriodPreset,
    describe_range,
    preset_range,
    previous_range,
)
from tg_sales.errors import TgSalesError
from tg_sales.services.kpis import DashboardData

router = APIRouter(tags=["dashboard"])


class PeriodView(BaseModel):
    preset: str
    label: str
    start: date
    end: date
    description: str


class DashboardView(BaseModel):
    period: PeriodView
    previous: PeriodView
    data: DashboardData


def resolve_period(
    today: date, preset: PeriodPreset, start: date | None, end: date | None
) -> DateRange:
    if preset is PeriodPreset.CUSTOM:
        if start is None or end is None:
            raise TgSalesError("Choose a start and an end date.", action="Pick both dates.")
        if start > end:
            raise TgSalesError(
                "The start date is after the end date.", action="Swap or correct the dates."
            )
        if (end - start).days > 366 * 10:
            raise TgSalesError("The period is too long.", action="Choose at most ten years.")
        return DateRange(start, end)
    return preset_range(preset, today)


def period_view(preset: PeriodPreset, dates: DateRange, label: str | None = None) -> PeriodView:
    return PeriodView(
        preset=preset.value,
        label=label or PRESET_LABELS.get(preset, "Custom range"),
        start=dates.start,
        end=dates.end,
        description=describe_range(dates),
    )


@router.get("/periods", response_model=list[PeriodView])
def periods(svc: Svc) -> list[PeriodView]:
    today = svc.kpis.today()
    return [
        period_view(preset, preset_range(preset, today))
        for preset in PeriodPreset
        if preset is not PeriodPreset.CUSTOM
    ]


@router.get("/dashboard", response_model=DashboardView)
def dashboard(
    svc: Svc,
    preset: PeriodPreset = PeriodPreset.LAST_30_DAYS,
    start: date | None = None,
    end: date | None = None,
    actor_id: str | None = None,
    lane: ProductLane | None = None,
) -> DashboardView:
    dates = resolve_period(svc.kpis.today(), preset, start, end)
    data = svc.kpis.dashboard(dates, KpiFilters(actor_id or None, lane))
    before = previous_range(dates)
    return DashboardView(
        period=period_view(preset, dates),
        previous=period_view(PeriodPreset.CUSTOM, before, "Previous period"),
        data=data,
    )


class ActorChoice(BaseModel):
    id: str
    name: str


@router.get("/dashboard/salespeople", response_model=list[ActorChoice])
def salespeople(svc: Svc) -> list[ActorChoice]:
    return [ActorChoice(id=i, name=n) for i, n in svc.kpis.actors()]
