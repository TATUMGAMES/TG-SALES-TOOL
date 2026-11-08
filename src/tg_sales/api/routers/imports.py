"""File import workflow: upload → read sheet → map columns → plan → decide → commit.

The uploaded file is kept in a private staging folder only while the import is
being prepared and is deleted when it is committed, cancelled or abandoned
(only its name, size, type and hash are kept afterwards). Reading, planning,
previewing and committing run as background jobs with progress and Cancel.
A backup is taken automatically before an import is committed.
"""

from __future__ import annotations

import re
import shutil
import tempfile
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from tg_sales.api.context import AppContext
from tg_sales.api.deps import Body, Ctx, JobRef, Ok, Svc, job_ref
from tg_sales.api.security import NotFoundError
from tg_sales.domain.importing import (
    FIELD_SPECS,
    ColumnMapping,
    ImportField,
    RecordOptions,
    mapping_problems,
    suggest_mapping,
)
from tg_sales.domain.normalization import DateOrder
from tg_sales.errors import TgSalesError
from tg_sales.services.import_files import (
    MAX_FILE_BYTES,
    SUPPORTED_EXTENSIONS,
    RawTable,
    SourceFile,
    inspect_file,
    read_table,
)
from tg_sales.services.imports import (
    Decision,
    ImportHistoryEntry,
    ImportPlan,
    UndoOutcome,
    export_issues_csv,
)

router = APIRouter(tags=["imports"])

SESSION_TTL_SECONDS = 4 * 3600
SAMPLE_ROWS = 25
PREVIEW_ROWS = 200


@dataclass
class ImportSession:
    id: str
    folder: Path
    source: SourceFile
    table: RawTable | None = None
    suggestions: list[ColumnMapping] = field(default_factory=list)
    plan: ImportPlan | None = None
    touched: float = field(default_factory=time.time)


class ImportSessions:
    def __init__(self, root: Path) -> None:
        self._root = root
        self._sessions: dict[str, ImportSession] = {}
        self._lock = threading.Lock()

    def add(self, session: ImportSession) -> None:
        with self._lock:
            self._expire()
            self._sessions[session.id] = session

    def get(self, session_id: str) -> ImportSession:
        with self._lock:
            found = self._sessions.get(session_id)
        if found is None:
            raise TgSalesError(
                "This import has expired or was already finished.",
                action="Start the import again by choosing the file.",
            )
        found.touched = time.time()
        return found

    def discard(self, session_id: str) -> None:
        with self._lock:
            found = self._sessions.pop(session_id, None)
        if found is not None:
            shutil.rmtree(found.folder, ignore_errors=True)

    def _expire(self) -> None:
        cutoff = time.time() - SESSION_TTL_SECONDS
        for session_id in [s.id for s in self._sessions.values() if s.touched < cutoff]:
            shutil.rmtree(self._sessions.pop(session_id).folder, ignore_errors=True)

    @property
    def root(self) -> Path:
        return self._root


def sessions_for(ctx: AppContext) -> ImportSessions:
    existing = getattr(ctx, "_import_sessions", None)
    if existing is None:
        existing = ImportSessions(ctx.paths.cache_dir / "import_staging")
        ctx._import_sessions = existing  # type: ignore[attr-defined]
    return existing


def _safe_name(name: str) -> str:
    base = Path(name.replace("\\", "/")).name
    cleaned = re.sub(r"[^\w.\- ()]+", "_", base).strip(" .") or "import"
    return cleaned[:120]


# ----------------------------------------------------------------- models
class UploadResult(BaseModel):
    session_id: str
    file_name: str
    kind: str
    size_bytes: int
    sheets: list[str]
    warnings: list[str]


class FieldView(BaseModel):
    field: str
    label: str
    multiple: bool


class MappingView(BaseModel):
    column: int
    header: str
    field: str | None
    confidence: float
    note: str


class TableView(BaseModel):
    headers: list[str]
    sample: list[list[str]]
    row_count: int
    description: str
    notes: list[str]
    reliable: bool
    problem: str | None
    sheet: str | None
    suggestions: list[MappingView]


class ReadIn(Body):
    sheet: str | None = None


class MappingIn(Body):
    column: int = Field(ge=0)
    field: ImportField | None


class PlanIn(Body):
    mappings: list[MappingIn] = Field(max_length=200)
    date_order: DateOrder = DateOrder.AUTO


class DecisionIn(Body):
    group_key: str
    decision: Decision
    target_id: str | None = None


class DecisionsIn(Body):
    decisions: list[DecisionIn] = Field(default_factory=list, max_length=100_000)
    all_unresolved: Decision | None = None


def _cell(value: object) -> str:
    return "" if value is None else str(value)


def _plan_view(plan: ImportPlan) -> dict[str, Any]:
    groups = []
    for group in plan.groups:
        action, target = group.effective()
        groups.append(
            {
                "key": group.key,
                "name": group.name,
                "rows": group.row_numbers,
                "action": group.action.value,
                "effective_action": action.value,
                "effective_target_id": target,
                "reason": group.reason,
                "target_id": group.target_id,
                "target_name": group.target_name,
                "needs_decision": group.needs_decision,
                "decision": group.decision.value if group.decision else None,
                "candidates": [
                    {"id": c.id, "name": c.name, "reason": c.reason, "strength": c.strength.value}
                    for c in group.candidates
                ],
                "contacts": sum(len(r.contacts) for r in group.records),
                "games": sum(1 for r in group.records if r.game),
            }
        )
    issues = plan.issues
    return {
        "job_id": plan.job_id,
        "groups": groups,
        "unresolved": len(plan.unresolved),
        "error_rows": len(plan.error_rows),
        "blank_rows": plan.blank_rows,
        "issues": [
            {
                "row": i.row_number,
                "severity": i.severity.value,
                "column": i.column,
                "message": i.message,
            }
            for i in issues[:PREVIEW_ROWS]
        ],
        "issue_count": len(issues),
        "previous_imports": [
            {"at": at.isoformat(), "file_name": name} for at, name in plan.previous_imports
        ],
    }


# ---------------------------------------------------------------- routes
@router.get("/imports/fields", response_model=list[FieldView])
def fields() -> list[FieldView]:
    return [FieldView(field=s.field.value, label=s.label, multiple=s.multiple) for s in FIELD_SPECS]


@router.post("/imports/upload", response_model=UploadResult)
async def upload(file: UploadFile, ctx: Ctx) -> UploadResult:
    name = _safe_name(file.filename or "import")
    if Path(name).suffix.lower() not in SUPPORTED_EXTENSIONS and not name.lower().endswith(
        (".xls", ".xlsm", ".xlsb", ".xltm")
    ):
        raise TgSalesError(
            "This type of file cannot be imported.",
            action="Choose a CSV, Excel (.xlsx) or text (.txt) file.",
        )
    sessions = sessions_for(ctx)
    sessions.root.mkdir(parents=True, exist_ok=True)
    folder = Path(tempfile.mkdtemp(prefix="import_", dir=sessions.root))
    path = folder / name
    size = 0
    try:
        with path.open("wb") as handle:
            while chunk := await file.read(1 << 20):
                size += len(chunk)
                if size > MAX_FILE_BYTES:
                    raise TgSalesError(
                        f"The file is larger than {MAX_FILE_BYTES // (1024 * 1024)} MB.",
                        action="Split the file into smaller files, or remove unused columns.",
                    )
                handle.write(chunk)
        source = inspect_file(path)
    except BaseException:
        shutil.rmtree(folder, ignore_errors=True)
        raise
    session = ImportSession(id=folder.name, folder=folder, source=source)
    sessions.add(session)
    return UploadResult(
        session_id=session.id,
        file_name=source.name,
        kind=source.kind.value,
        size_bytes=source.size_bytes,
        sheets=list(source.sheet_names),
        warnings=list(source.warnings),
    )


@router.post("/imports/{session_id}/read", response_model=JobRef)
def read(session_id: str, body: ReadIn, ctx: Ctx) -> JobRef:
    session = sessions_for(ctx).get(session_id)

    def work(token, progress):  # type: ignore[no-untyped-def]
        table = read_table(session.source, body.sheet, token, progress)
        session.table, session.plan = table, None
        session.suggestions = (
            suggest_mapping(table.headers, table.rows[:50]) if table.reliable else []
        )
        return TableView(
            headers=table.headers,
            sample=[[_cell(v) for v in row] for row in table.rows[:SAMPLE_ROWS]],
            row_count=len(table.rows),
            description=table.description,
            notes=list(table.notes),
            reliable=table.reliable,
            problem=table.problem,
            sheet=table.sheet_name,
            suggestions=[
                MappingView(
                    column=m.column,
                    header=m.header,
                    field=m.field.value if m.field else None,
                    confidence=m.confidence,
                    note=m.note,
                )
                for m in session.suggestions
            ],
        ).model_dump()

    return job_ref(ctx.jobs.submit("import-read", work))


@router.post("/imports/{session_id}/plan", response_model=JobRef)
def plan(session_id: str, body: PlanIn, ctx: Ctx, svc: Svc) -> JobRef:
    session = sessions_for(ctx).get(session_id)
    if session.table is None:
        raise TgSalesError("Read the file first.", action="Go back to the first step.")
    headers = session.table.headers
    mappings = [
        ColumnMapping(m.column, headers[m.column] if m.column < len(headers) else "", m.field, 1.0)
        for m in body.mappings
        if m.column < len(headers)
    ]
    problems = mapping_problems(mappings)
    if problems:
        raise TgSalesError(problems[0], action="Adjust the column choices and continue.")
    table = session.table

    def work(token, progress):  # type: ignore[no-untyped-def]
        planned = svc.imports.plan(
            session.source,
            table,
            mappings,
            RecordOptions(date_order=body.date_order),
            token,
            progress,
        )
        session.plan = planned
        return _plan_view(planned)

    return job_ref(ctx.jobs.submit("import-plan", work))


@router.post("/imports/{session_id}/decisions")
def decide(session_id: str, body: DecisionsIn, ctx: Ctx) -> dict[str, Any]:
    session = sessions_for(ctx).get(session_id)
    if session.plan is None:
        raise TgSalesError("Check the rows first.", action="Go back to the mapping step.")
    groups = {g.key: g for g in session.plan.groups}
    for item in body.decisions:
        group = groups.get(item.group_key)
        if group is None:
            raise NotFoundError("That group of rows")
        try:
            group.decide(item.decision, item.target_id)
        except ValueError as exc:
            raise TgSalesError(str(exc), action="Choose one of the suggested prospects.") from exc
    if body.all_unresolved is not None:
        try:
            session.plan.decide_all_unresolved(body.all_unresolved)
        except ValueError as exc:
            raise TgSalesError(str(exc), action="Choose a target for each merge.") from exc
    return _plan_view(session.plan)


def _outcome(outcome: Any) -> dict[str, Any]:
    counts = outcome.counts
    return {
        "job_id": outcome.job_id,
        "committed": outcome.committed,
        "counts": {
            "organizations_created": counts.organizations_created,
            "organizations_updated": counts.organizations_updated,
            "organizations_skipped": counts.organizations_skipped,
            "contacts_created": counts.contacts_created,
            "contacts_updated": counts.contacts_updated,
            "games_created": counts.games_created,
            "error_rows": counts.error_rows,
            "warnings": counts.warnings,
        },
        "issues": [
            {
                "row": i.row_number,
                "severity": i.severity.value,
                "column": i.column,
                "message": i.message,
            }
            for i in outcome.issues[:PREVIEW_ROWS]
        ],
        "issue_count": len(outcome.issues),
    }


@router.post("/imports/{session_id}/preview", response_model=JobRef)
def preview(session_id: str, ctx: Ctx, svc: Svc) -> JobRef:
    session = sessions_for(ctx).get(session_id)
    planned = session.plan
    if planned is None:
        raise TgSalesError("Check the rows first.", action="Go back to the mapping step.")

    def work(token, progress):  # type: ignore[no-untyped-def]
        return _outcome(svc.imports.preview(planned, token, progress))

    return job_ref(ctx.jobs.submit("import-preview", work))


@router.post("/imports/{session_id}/commit", response_model=JobRef)
def commit(session_id: str, ctx: Ctx, svc: Svc) -> JobRef:
    sessions = sessions_for(ctx)
    session = sessions.get(session_id)
    planned = session.plan
    if planned is None:
        raise TgSalesError("Check the rows first.", action="Go back to the mapping step.")
    if planned.unresolved:
        raise TgSalesError(
            f"{len(planned.unresolved)} prospects still need a decision.",
            action="Choose create, merge or skip for each highlighted prospect.",
        )

    def work(token, progress):  # type: ignore[no-untyped-def]
        progress(2, "Backing up your data…")
        backup = ctx.backup_before("pre-import")
        outcome = svc.imports.commit(planned, token, progress)
        sessions.discard(session_id)
        return {**_outcome(outcome), "backup": backup.name if backup else None}

    return job_ref(ctx.jobs.submit("import-commit", work, exclusive=True))


@router.get("/imports/{session_id}/problems.csv")
def problems_csv(session_id: str, ctx: Ctx, background: BackgroundTasks) -> FileResponse:
    session = sessions_for(ctx).get(session_id)
    if session.plan is None:
        raise TgSalesError("There are no problems to export yet.", action="Check the rows first.")
    path = session.folder / "problems.csv"
    export_issues_csv(path, session.plan, session.plan.issues)
    return FileResponse(path, media_type="text/csv", filename="import_problems.csv")


@router.delete("/imports/{session_id}", response_model=Ok)
def cancel(session_id: str, ctx: Ctx) -> Ok:
    sessions_for(ctx).discard(session_id)
    return Ok()


@router.get("/imports/history", response_model=list[ImportHistoryEntry])
def history(svc: Svc) -> list[ImportHistoryEntry]:
    return svc.imports.history()


@router.post("/imports/history/{job_id}/undo", response_model=UndoOutcome)
def undo(job_id: str, svc: Svc) -> UndoOutcome:
    return svc.imports.undo(job_id)
