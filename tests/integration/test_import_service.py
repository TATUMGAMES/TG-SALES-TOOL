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

import csv
import time
from pathlib import Path

import pytest
from sqlalchemy import func, select

from tg_sales.cancellation import CancelToken, OperationCancelledError
from tg_sales.db.database import Database
from tg_sales.db.models import Activity, Contact, Game, ImportChange, ImportJob, Organization
from tg_sales.domain.enums import ActivityType, ContactStatus, ProductLane, RecordSource
from tg_sales.domain.importing import RecordOptions, suggest_mapping
from tg_sales.domain.prospects import ContactDraft, OrganizationDraft, ProspectQuery
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.services import imports as imports_module
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.import_files import inspect_file, read_table
from tg_sales.services.imports import (
    Decision,
    ImportFailedError,
    ImportPlan,
    ImportService,
    PlanAction,
    export_issues_csv,
)
from tg_sales.services.ledger import ActivityLedger
from tg_sales.services.opportunities import OpportunityService
from tg_sales.services.prospects import ProspectService

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"


@pytest.fixture
def actor(database: Database) -> str:
    return ensure_local_actor(database)


@pytest.fixture
def service(database: Database, actor: str) -> ImportService:
    return ImportService(database, actor)


@pytest.fixture
def prospects(database: Database, actor: str) -> ProspectService:
    return ProspectService(database, actor)


def plan_file(service: ImportService, path: Path, sheet: str | None = None) -> ImportPlan:
    source = inspect_file(path)
    table = read_table(source, sheet)
    return service.plan(source, table, suggest_mapping(table.headers, table.rows[:50]))


def plan_csv(
    service: ImportService, tmp_path: Path, text: str, name: str = "list.csv"
) -> ImportPlan:
    path = tmp_path / name
    path.write_text(text, encoding="utf-8")
    return plan_file(service, path)


def count(database: Database, model: type, *conditions: object) -> int:
    with database.session() as session:
        query = select(func.count()).select_from(model).where(*conditions)  # type: ignore[arg-type]
        return int(session.scalar(query) or 0)


def live(model: type) -> object:
    return model.deleted_at_utc.is_(None)  # type: ignore[attr-defined]


def test_messy_fixture_end_to_end(database: Database, service: ImportService) -> None:
    plan = plan_file(service, FIXTURES / "messy_prospects.csv")
    assert not plan.unresolved
    assert [r.row_number for r in plan.error_rows] == [10]
    preview = service.preview(plan)
    assert not preview.committed
    assert count(database, Organization) == 0  # the trial run saved nothing
    outcome = service.commit(plan)
    assert outcome.committed
    assert outcome.counts == preview.counts
    c = outcome.counts
    # Pixel Forge (2 rows), Moon Owl (duplicate rows), Sakura, Éclair, Northwind,
    # Twin Peaks and Solo Dev
    assert c.organizations_created == 7
    assert c.error_rows == 1
    assert c.contacts_created == 9
    assert c.games_created == 5
    with database.session() as session:
        pixel = session.scalars(
            select(Organization).where(Organization.domain == "pixelforge.example")
        ).one()
        assert pixel.source is RecordSource.IMPORT
        assert pixel.tags == ["indie", "vr"]
        contacts = session.scalars(select(Contact).where(Contact.organization_id == pixel.id)).all()
        statuses = {c.name: c.contact_status for c in contacts}
        assert statuses == {
            "Ana Ruiz": ContactStatus.ATTEMPTED,
            "Bo Lind": ContactStatus.NOT_CONTACTED,
        }
        assert all(c.provenance == "Imported from messy_prospects.csv" for c in contacts)
        moon_contacts = session.scalars(
            select(Contact).join(Organization).where(Organization.name == "Moon Owl Games")
        ).all()
        assert len(moon_contacts) == 1  # the duplicate row did not create a second contact
        job = session.scalars(select(ImportJob)).one()
        assert job.file_name == "messy_prospects.csv"
        assert job.status == "committed"
        assert job.error_count == 1
        assert job.error_summary is not None and "No studio" in job.error_summary
        assert "@" not in (job.error_summary or "")  # no row values stored
        assert job.mapping["columns"][0] == {"header": "Studio", "field": "organization_name"}
        event = session.scalars(
            select(Activity).where(Activity.type == ActivityType.IMPORT_COMMITTED)
        ).one()
        assert event.payload["created"] == 7


def test_xlsx_fixture_with_sheet(database: Database, service: ImportService) -> None:
    plan = plan_file(service, FIXTURES / "sample_prospects.xlsx", "Prospects")
    outcome = service.commit(plan)
    assert outcome.counts.organizations_created == 4
    assert outcome.counts.contacts_created == 4
    with database.session() as session:
        aurora = session.scalars(
            select(Organization).where(Organization.name == "Aurora Bay Games")
        ).one()
        game = session.scalars(select(Game).where(Game.title == "Northern Drift")).one()
        assert game.platform == "PC"
        assert str(game.release_date) == "2027-05-20"
        assert aurora.website == "https://aurorabay.example"


def test_reimport_is_idempotent(database: Database, service: ImportService) -> None:
    service.commit(plan_file(service, FIXTURES / "messy_prospects.csv"))
    before = (count(database, Organization), count(database, Contact), count(database, Game))
    again = plan_file(service, FIXTURES / "messy_prospects.csv")
    assert again.previous_imports
    assert {g.action for g in again.groups} == {PlanAction.SKIP}
    outcome = service.commit(again)
    assert outcome.counts.organizations_created == 0
    assert outcome.counts.organizations_updated == 0
    assert (
        count(database, Organization),
        count(database, Contact),
        count(database, Game),
    ) == before


def test_matching_existing_prospects_fills_only_missing_details(
    database: Database, service: ImportService, prospects: ProspectService, tmp_path: Path
) -> None:
    existing = prospects.create(
        OrganizationDraft("Pixel Forge Studios", "pixelforge.example", location="Lisbon"),
        [ContactDraft(name="Ana Ruiz", email="ana@pixelforge.example")],
    )
    plan = plan_csv(
        service,
        tmp_path,
        "Studio,Website,Location,Country,Contact,Email,Contacted,Tags\n"
        "Pixel Forge,https://www.pixelforge.example/,Porto,Portugal,Ana Ruiz,"
        "ANA@pixelforge.example,yes,partner\n",
    )
    (group,) = plan.groups
    assert group.action is PlanAction.UPDATE
    assert group.target_id == existing
    outcome = service.commit(plan)
    assert outcome.counts.organizations_updated == 1
    assert outcome.counts.contacts_updated == 1
    detail = prospects.get_detail(existing)
    assert detail is not None
    assert detail.location == "Lisbon"  # never overwritten
    assert detail.country == "Portugal"  # empty field filled
    assert detail.tags == ("partner",)
    assert detail.contacts[0].status is ContactStatus.ATTEMPTED
    messages = [i.message for i in outcome.issues]
    assert any("Kept the existing location" in m for m in messages)
    assert not any("website" in m.lower() for m in messages)  # same domain, different spelling


def test_similar_names_need_a_decision(
    service: ImportService, prospects: ProspectService, tmp_path: Path
) -> None:
    prospects.create(OrganizationDraft("Moon Owl Games", "moonowl.example"))
    plan = plan_csv(
        service,
        tmp_path,
        "Studio,Website\n"
        "Moon Owl Games,moon-owl-games.example\n"
        "Moon Owl Game,\n"
        "Brand New,new.example\n",
    )
    actions = {g.name: g.action for g in plan.groups}
    assert actions == {
        "Moon Owl Games": PlanAction.REVIEW,  # same name, different website
        "Moon Owl Game": PlanAction.REVIEW,  # similar name
        "Brand New": PlanAction.CREATE,
    }
    with pytest.raises(ImportFailedError, match="need a decision"):
        service.commit(plan)
    first, second = plan.unresolved
    with pytest.raises(ValueError, match="candidates"):
        first.decide(Decision.MERGE, "not-a-candidate")
    first.decide(Decision.CREATE_NEW)
    second.decide(Decision.MERGE, second.candidates[0].id)
    outcome = service.commit(plan)
    assert outcome.counts.organizations_created == 2
    assert outcome.counts.organizations_skipped == 1  # merged but nothing new to add
    assert prospects.count() == 3


def test_saving_the_same_plan_twice_is_refused(service: ImportService, tmp_path: Path) -> None:
    plan = plan_csv(service, tmp_path, "Studio\nA Studio\n")
    service.commit(plan)
    with pytest.raises(ImportFailedError, match="already been saved"):
        service.commit(plan)


def test_failure_rolls_back_everything(
    database: Database, service: ImportService, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    plan = plan_csv(service, tmp_path, "Studio\nOne\nTwo\nThree\n")
    original = imports_module._apply_group
    calls = {"n": 0}

    def flaky(ctx: object, group: object) -> None:
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("disk full")
        original(ctx, group)  # type: ignore[arg-type]

    monkeypatch.setattr(imports_module, "_apply_group", flaky)
    with pytest.raises(ImportFailedError) as info:
        service.commit(plan)
    assert "Nothing was changed" in info.value.user_message
    assert count(database, Organization) == 0
    assert count(database, ImportJob) == 0
    assert count(database, Activity) == 0


def test_cancel_saves_nothing(database: Database, service: ImportService, tmp_path: Path) -> None:
    plan = plan_csv(service, tmp_path, "Studio\n" + "".join(f"Studio {i}\n" for i in range(50)))
    token = CancelToken()
    seen = []

    def progress(percent: int, _message: str) -> None:
        seen.append(percent)
        if percent >= 50:
            token.cancel()

    with pytest.raises(OperationCancelledError):
        service.commit(plan, token, progress)
    assert seen
    assert count(database, Organization) == 0
    assert count(database, ImportJob) == 0


def test_undo_reverts_creates_and_updates(
    database: Database, service: ImportService, prospects: ProspectService, tmp_path: Path
) -> None:
    existing = prospects.create(OrganizationDraft("Pixel Forge", "pixelforge.example"))
    plan = plan_csv(
        service,
        tmp_path,
        "Studio,Website,Country,Contact,Game,Tags\n"
        "Pixel Forge,pixelforge.example,Portugal,Bo,Sky Rails,vr\n"
        "Moon Owl,moonowl.example,,Chloé,Owl Quest,\n",
    )
    outcome = service.commit(plan)
    assert prospects.count() == 2
    result = service.undo(outcome.job_id)
    assert result.kept == 0
    assert result.reverted > 0
    assert prospects.count() == 1
    detail = prospects.get_detail(existing)
    assert detail is not None
    assert detail.country is None
    assert detail.tags == ()
    assert detail.contacts == ()
    assert detail.games == ()
    assert count(database, Contact, live(Contact)) == 0
    history = service.history()
    assert history[0].status == "undone" and history[0].undone_at is not None
    assert not history[0].can_undo
    with pytest.raises(ImportFailedError, match="cannot be undone"):
        service.undo(outcome.job_id)
    # after undo the same rows are imported again instead of being skipped as known
    again = plan_csv(
        service,
        tmp_path,
        "Studio,Website,Country,Contact,Game,Tags\n"
        "Pixel Forge,pixelforge.example,Portugal,Bo,Sky Rails,vr\n"
        "Moon Owl,moonowl.example,,Chloé,Owl Quest,\n",
        name="again.csv",
    )
    assert {g.action for g in again.groups} == {PlanAction.UPDATE, PlanAction.CREATE}


def test_undo_keeps_records_changed_after_the_import(
    database: Database,
    service: ImportService,
    prospects: ProspectService,
    actor: str,
    tmp_path: Path,
) -> None:
    plan = plan_csv(
        service,
        tmp_path,
        "Studio,Website,Contact\n"
        "Edited Co,edited.example,Ana\n"
        "Deal Co,deal.example,\n"
        "Plain Co,plain.example,\n",
    )
    outcome = service.commit(plan)
    ids = {r.name: r.id for r in prospects.search(ProspectQuery()).rows}
    prospects.update(
        ids["Edited Co"], OrganizationDraft("Edited Co", "edited.example", notes="Met at GDC")
    )
    with database.session() as session:
        ledger = ActivityLedger(session, actor, database.clock)
        OpportunityService(session, ledger, database.clock).create(
            organization_id=ids["Deal Co"],
            product_lane=ProductLane.DATA_LICENSING,
            stage_id=DEFAULT_STAGES[0].id,
        )
    result = service.undo(outcome.job_id)
    assert result.kept >= 2
    remaining = {r.name for r in prospects.search(ProspectQuery()).rows}
    assert remaining == {"Edited Co", "Deal Co"}


def test_issues_csv_escapes_formulas(service: ImportService, tmp_path: Path) -> None:
    plan = plan_file(service, FIXTURES / "messy_prospects.csv")
    outcome = service.preview(plan)
    target = tmp_path / "out" / "problems.csv"
    written = export_issues_csv(target, plan, outcome.issues)
    assert written == len(outcome.issues)
    raw = target.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")
    with target.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    assert rows[0][:4] == ["Row", "Severity", "Column", "Problem"]
    order = [(int(r[0]), r[1] != "error") for r in rows[1:]]
    assert order == sorted(order)  # by row, errors before warnings within a row
    assert ("10", "error") in [(r[0], r[1]) for r in rows[1:]]
    cells = [cell for row in rows for cell in row]
    assert '\'=HYPERLINK("http://evil.example")' in cells
    assert not any(cell.startswith("=") for cell in cells)


def test_options_change_date_reading(service: ImportService, tmp_path: Path) -> None:
    path = tmp_path / "d.csv"
    path.write_text("Studio,Game,Release Date\nA,G,03/04/2027\n", encoding="utf-8")
    source = inspect_file(path)
    table = read_table(source)
    mapping = suggest_mapping(table.headers)
    from tg_sales.domain.normalization import DateOrder

    plan = service.plan(source, table, mapping, RecordOptions(DateOrder.DAY_FIRST))
    record = plan.groups[0].records[0]
    assert record.game is not None and str(record.game.release_date) == "2027-04-03"


def test_large_file_performance(database: Database, service: ImportService, tmp_path: Path) -> None:
    rows = ["Studio,Website,Contact,Email,Contacted,Game"]
    rows += [
        f"Studio {i},studio{i}.example,Person {i},p{i}@studio{i}.example,"
        f"{'yes' if i % 2 else ''},Game {i}"
        for i in range(5000)
    ]
    started = time.perf_counter()
    plan = plan_csv(service, tmp_path, "\n".join(rows) + "\n", name="large.csv")
    outcome = service.commit(plan)
    elapsed = time.perf_counter() - started
    assert outcome.counts.organizations_created == 5000
    assert outcome.counts.contacts_created == 5000
    assert elapsed < 60, f"5,000-row import took {elapsed:.1f}s"
    assert count(database, ImportChange) >= 15000
