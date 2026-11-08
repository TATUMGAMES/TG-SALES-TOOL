"""Shared FastAPI dependencies and helpers for routers."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Depends, Request
from pydantic import BaseModel, ConfigDict

from tg_sales.api.context import AppContext, Services
from tg_sales.api.jobs import Job


def get_context(request: Request) -> AppContext:
    context: AppContext = request.app.state.context
    return context


def get_services(request: Request) -> Services:
    return get_context(request).services


Ctx = Annotated[AppContext, Depends(get_context)]
Svc = Annotated[Services, Depends(get_services)]


class Body(BaseModel):
    """Base for request bodies: unknown fields are rejected, text is trimmed."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class JobRef(BaseModel):
    job_id: str
    kind: str
    status: str


class JobView(BaseModel):
    id: str
    kind: str
    status: str
    percent: int
    message: str
    result: Any = None
    error: dict[str, str] | None = None


def job_ref(job: Job) -> JobRef:
    return JobRef(job_id=job.id, kind=job.kind, status=job.status.value)


class Ok(BaseModel):
    ok: bool = True
    count: int | None = None
    id: str | None = None
