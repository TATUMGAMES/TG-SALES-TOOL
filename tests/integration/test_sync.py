"""Offline collaboration between simulated computers (each its own database)."""

from __future__ import annotations

import io
import json
import zipfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest
from sqlalchemy import func, select, text

from tg_sales.db.database import Database
from tg_sales.db.models import Contact, Organization, PipelineStage
from tg_sales.domain.enums import ActivityType, ProductLane
from tg_sales.domain.kpi import KpiFilters
from tg_sales.domain.opportunities import OpportunityDraft
from tg_sales.domain.periods import DateRange
from tg_sales.domain.prospects import ContactDraft, OrganizationDraft
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.kpis import KpiService
from tg_sales.services.pipeline import PipelineService
from tg_sales.services.prospects import ProspectService
from tg_sales.sync.engine import SyncError, SyncService
from tg_sales.sync.package import PackageError

from .conftest import FakeClock

pytestmark = pytest.mark.integration

STAGE = {s.key: s.id for s in DEFAULT_STAGES}


@dataclass
class Computer:
    name: str
    db: Database
    sync: SyncService
    prospects: ProspectService
    pipeline: PipelineService
    folder: Path

    def export(self, *, full: bool = False, passphrase: str | None = None) -> Path:
        return self.sync.export(self.folder, full=full, passphrase=passphrase).path

    def receive(
        self,
        package: Path,
        passphrase: str | None = None,
        resolutions: dict[str, dict[str, str]] | None = None,
    ):  # type: ignore[no-untyped-def]
        preview = self.sync.stage(package.read_bytes(), package.name, passphrase)
        return preview, self.sync.apply(preview.token, resolutions)

    def names(self) -> list[str]:
        with self.db.session() as session:
            return sorted(
                session.scalars(
                    select(Organization.name).where(Organization.deleted_at_utc.is_(None))
                )
            )

    def count(self, table: str) -> int:
        with self.db.engine.connect() as connection:
            return int(connection.scalar(text(f"SELECT count(*) FROM {table}")) or 0)  # noqa: S608


@pytest.fixture
def make_computer(
    make_database: Callable[..., Database], clock: FakeClock, tmp_path: Path
) -> Callable[[str], Computer]:
    def factory(name: str) -> Computer:
        db = make_database(clock)
        actor = ensure_local_actor(db)
        return Computer(
            name,
            db,
            SyncService(db, actor, lambda: name, staging_dir=tmp_path / f"staging {name}"),
            ProspectService(db, actor),
            PipelineService(db, actor),
            tmp_path / f"packages {name}",
        )

    return factory


def test_two_computers_converge(make_computer: Callable[[str], Computer]) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    a.prospects.create(
        OrganizationDraft("Alpha Studio"), [ContactDraft(name="Ann", email="ann@alpha.example")]
    )
    b.prospects.create(OrganizationDraft("Beta Games"))

    b.receive(a.export())
    a.receive(b.export())

    assert a.names() == b.names() == ["Alpha Studio", "Beta Games"]
    assert a.count("contacts") == b.count("contacts") == 1
    assert a.count("activities") == b.count("activities")


def test_same_package_twice_changes_nothing(make_computer: Callable[[str], Computer]) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    org = a.prospects.create(OrganizationDraft("Alpha Studio"))
    a.pipeline.create_opportunity(
        OpportunityDraft(org, ProductLane.DATA_LICENSING, STAGE["contacted"])
    )
    package = a.export()
    b.receive(package)
    counts = {t: b.count(t) for t in ("organizations", "opportunities", "activities", "change_log")}
    preview, result = b.receive(package)
    assert preview.already_imported
    assert set(result.counts) <= {"skip", "pending_applied"}
    assert {t: b.count(t) for t in counts} == counts
    assert b.count("sync_imports") == 1


def test_concurrent_edits_surface_conflict_and_resolution_propagates(
    make_computer: Callable[[str], Computer],
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    org = a.prospects.create(OrganizationDraft("Shared Studio", location="Paris"))
    b.receive(a.export())

    a.prospects.update(org, OrganizationDraft("Shared Studio", location="Lyon"))
    b.prospects.update(org, OrganizationDraft("Shared Studio", location="Berlin"))

    preview = b.sync.stage(a.export().read_bytes(), "from-a.zip")
    conflict = next(c for c in preview.conflicts if c.table == "organizations")
    fields = {d.field: (d.local, d.incoming) for d in conflict.differences}
    assert fields["location"] == ("Berlin", "Lyon")
    with pytest.raises(SyncError, match="not been resolved"):
        b.sync.apply(preview.token, {})
    resolution = {conflict.key: {f: "local" for f in fields} | {"location": "incoming"}}
    b.sync.apply(preview.token, resolution)
    with b.db.session() as session:
        assert session.get(Organization, org).location == "Lyon"  # type: ignore[union-attr]
    assert b.count("conflicts") == len(fields)

    # B's merged version reaches A without a new conflict.
    preview_back, _ = a.receive(b.export())
    assert preview_back.conflicts == ()
    with a.db.session() as session:
        assert session.get(Organization, org).location == "Lyon"  # type: ignore[union-attr]


def test_identical_concurrent_edits_converge_without_conflict(
    make_computer: Callable[[str], Computer],
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    org = a.prospects.create(OrganizationDraft("Same Studio"))
    b.receive(a.export())
    a.prospects.update(org, OrganizationDraft("Same Studio", country="Japan"))
    b.prospects.update(org, OrganizationDraft("Same Studio", country="Japan"))
    preview, _ = b.receive(a.export())
    assert preview.conflicts == ()


def test_propagation_a_b_c_a_without_loops(make_computer: Callable[[str], Computer]) -> None:
    a, b, c = make_computer("Alice"), make_computer("Bob"), make_computer("Cara")
    a.prospects.create(OrganizationDraft("From Alice"))
    b.receive(a.export())
    b.prospects.create(OrganizationDraft("From Bob"))
    c.receive(b.export())
    assert c.names() == ["From Alice", "From Bob"]
    c.prospects.create(OrganizationDraft("From Cara"))
    before = a.count("change_log")
    preview, _ = a.receive(c.export(full=True))
    assert a.names() == ["From Alice", "From Bob", "From Cara"]
    # Alice's own studio came back unchanged: recognized, not re-applied.
    assert preview.by_table["organizations"].get("skip", 0) == 1
    assert preview.conflicts == ()
    assert a.count("change_log") > before
    # Exporting again from Alice to Cara sends nothing Cara does not already have.
    preview_c, _ = c.receive(a.export())
    assert set(preview_c.counts) <= {"skip", "converge"}


def test_tombstones_and_archived_stage_propagate(make_computer: Callable[[str], Computer]) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    org = a.prospects.create(OrganizationDraft("Studio"), [ContactDraft(name="Old Contact")])
    stage = a.pipeline.create_stage("Pilot", lane=ProductLane.DATA_LICENSING)
    opp = a.pipeline.create_opportunity(OpportunityDraft(org, ProductLane.DATA_LICENSING, stage))
    b.receive(a.export())

    detail = a.prospects.get_detail(org)
    assert detail is not None
    a.prospects.set_contact_archived(detail.contacts[0].id, True)
    a.pipeline.archive_stage(stage, STAGE["contacted"])
    b.receive(a.export())

    with b.db.session() as session:
        contact = session.scalars(select(Contact)).one()
        assert contact.archived_at_utc is not None
        assert session.get(PipelineStage, stage).archived_at_utc is not None  # type: ignore[union-attr]
    assert b.pipeline.detail(opp).stage.id == STAGE["contacted"]  # type: ignore[union-attr]


def test_out_of_order_packages_wait_for_missing_records(
    make_computer: Callable[[str], Computer], clock: FakeClock
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    org = a.prospects.create(OrganizationDraft("Early Studio"))
    first = a.export()
    a.pipeline.create_opportunity(
        OpportunityDraft(org, ProductLane.PUBLISHER_PARTNERSHIP, STAGE["contacted"])
    )
    second = a.export()

    preview, result = b.receive(second)
    assert preview.counts.get("pending", 0) >= 1
    assert result.pending_remaining >= 1
    assert b.count("opportunities") == 0

    _, result_first = b.receive(first)
    assert result_first.pending_applied >= 1
    assert result_first.pending_remaining == 0
    assert b.count("opportunities") == 1
    assert b.sync.pending_count() == 0


def test_dashboards_agree_after_merge(
    make_computer: Callable[[str], Computer], clock: FakeClock
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    clock.set(datetime(2026, 10, 5, 12, tzinfo=UTC))
    org_a = a.prospects.create(
        OrganizationDraft("Alpha"), [ContactDraft(name="A", email="a@alpha.example")]
    )
    opp_a = a.pipeline.create_opportunity(
        OpportunityDraft(org_a, ProductLane.DATA_LICENSING, STAGE["contacted"])
    )
    a.pipeline.log_activity(opp_a, ActivityType.EMAIL, note="hello")
    org_b = b.prospects.create(OrganizationDraft("Beta"))
    opp_b = b.pipeline.create_opportunity(
        OpportunityDraft(org_b, ProductLane.PUBLISHER_PARTNERSHIP, STAGE["contacted"])
    )
    clock.set(clock.current + timedelta(days=2))
    b.pipeline.move(opp_b, STAGE["won"], reason_code="signed")
    b.receive(a.export())
    a.receive(b.export())

    period = DateRange(date(2026, 10, 1), date(2026, 10, 31))

    def numbers(db: Database) -> dict[str, float | None]:
        report = KpiService(db, zone=UTC).dashboard(period, KpiFilters()).report
        return {k: m.value for k, m in report.metrics.items()}

    assert numbers(a.db) == numbers(b.db)
    assert numbers(a.db)["won"] == 1


def test_encrypted_package_round_trip_and_wrong_passphrase(
    make_computer: Callable[[str], Computer],
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    a.prospects.create(
        OrganizationDraft("Secret Studio"), [ContactDraft(email="boss@secret.example")]
    )
    package = a.export(passphrase="correct horse battery")
    raw = package.read_bytes()
    assert b"Secret Studio" not in raw and b"secret.example" not in raw
    with pytest.raises(PackageError, match="encrypted"):
        b.sync.stage(raw, package.name)
    with pytest.raises(PackageError, match="passphrase is wrong"):
        b.sync.stage(raw, package.name, "wrong passphrase!!")
    preview, _ = b.receive(package, "correct horse battery")
    assert preview.encrypted
    assert b.names() == ["Secret Studio"]
    with pytest.raises(PackageError, match="at least"):
        a.export(full=True, passphrase="short")


def _zip(members: dict[str, bytes], compression: int = zipfile.ZIP_DEFLATED) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression) as archive:
        for name, data in members.items():
            archive.writestr(name, data)
    return buffer.getvalue()


def _manifest(**extra: object) -> bytes:
    data = {"format": "tg_sales_sync", "format_version": 1, "files": {}} | extra
    return json.dumps(data).encode()


@pytest.mark.parametrize(
    ("data", "message"),
    [
        (b"not a zip at all", "not a valid ZIP"),
        (_zip({"../evil.txt": b"x", "manifest.json": _manifest()}), "unexpected files"),
        (_zip({"C:/Windows/evil.jsonl": b"x", "manifest.json": _manifest()}), "unexpected files"),
        (
            _zip({"changes/organizations.jsonl": b"0" * 5_000_000, "manifest.json": _manifest()}),
            "suspiciously compressed",
        ),
        (_zip({"notes.txt": b"x"}), "unexpected files"),
        (_zip({"manifest.json": b"{nope"}), "manifest is damaged"),
        (_zip({"manifest.json": _manifest(format_version=99)}), "newer version"),
        (
            _zip(
                {
                    "manifest.json": _manifest(
                        files={"changes/organizations.jsonl": {"sha256": "0" * 64}}
                    ),
                    "changes/organizations.jsonl": b"{}\n",
                }
            ),
            "checksum",
        ),
    ],
)
def test_unsafe_or_damaged_packages_are_refused(
    make_computer: Callable[[str], Computer], data: bytes, message: str
) -> None:
    b = make_computer("Bob")
    with pytest.raises(PackageError, match=message):
        b.sync.stage(data, "package.zip")
    assert b.count("organizations") == 0


def test_schema_mismatch_and_own_package_are_refused(
    make_computer: Callable[[str], Computer],
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    a.prospects.create(OrganizationDraft("Studio"))
    package = a.export()
    with pytest.raises(SyncError, match="this computer"):
        a.sync.stage(package.read_bytes(), package.name)
    with zipfile.ZipFile(package) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    manifest = json.loads(members["manifest.json"])
    manifest["schema_revision"] = "9999"
    members["manifest.json"] = json.dumps(manifest).encode()
    with pytest.raises(PackageError, match="different version"):
        b.sync.stage(_zip(members), package.name)


def test_invalid_record_values_are_refused(make_computer: Callable[[str], Computer]) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    a.prospects.create(OrganizationDraft("Studio"))
    package = a.export()
    with zipfile.ZipFile(package) as archive:
        members = {n: archive.read(n) for n in archive.namelist()}
    line = json.loads(members["changes/organizations.jsonl"].decode().splitlines()[0])
    line["row"]["company_type"] = "spaceship"
    content = (json.dumps(line) + "\n").encode()
    members["changes/organizations.jsonl"] = content
    manifest = json.loads(members["manifest.json"])
    import hashlib

    manifest["files"]["changes/organizations.jsonl"]["sha256"] = hashlib.sha256(content).hexdigest()
    members["manifest.json"] = json.dumps(manifest).encode()
    with pytest.raises(PackageError, match="cannot read"):
        b.sync.stage(_zip(members), package.name)


def test_interrupted_import_rolls_back(
    make_computer: Callable[[str], Computer], monkeypatch: pytest.MonkeyPatch
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    for index in range(3):
        a.prospects.create(OrganizationDraft(f"Studio {index}"))
    preview = b.sync.stage(a.export().read_bytes(), "a.zip")
    calls = {"n": 0}
    original = SyncService._apply_record

    def explode(self, connection, record, *args):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("power cut")
        return original(self, connection, record, *args)

    monkeypatch.setattr(SyncService, "_apply_record", explode)
    with pytest.raises(RuntimeError):
        b.sync.apply(preview.token)
    assert b.count("organizations") == 0
    assert b.count("sync_imports") == 0
    monkeypatch.undo()
    b.sync.apply(preview.token)
    assert b.count("organizations") == 3


def test_nothing_new_to_export(make_computer: Callable[[str], Computer]) -> None:
    a = make_computer("Alice")
    a.prospects.create(OrganizationDraft("Studio"))
    a.export()
    with pytest.raises(SyncError, match="no new changes"):
        a.export()
    assert a.export(full=True).is_file()


def test_possible_duplicates_are_flagged_not_merged(
    make_computer: Callable[[str], Computer],
) -> None:
    a, b = make_computer("Alice"), make_computer("Bob")
    a.prospects.create(OrganizationDraft("Twin Studio", website="https://twin.example"))
    b.prospects.create(OrganizationDraft("Twin Studio", website="https://twin.example"))
    preview, _ = b.receive(a.export())
    assert any(d.reason == "same website domain" for d in preview.possible_duplicates)
    with b.db.session() as session:
        assert session.scalar(select(func.count()).select_from(Organization)) == 2


def test_recipient_mismatch_is_warned(make_computer: Callable[[str], Computer]) -> None:
    a, b, c = make_computer("Alice"), make_computer("Bob"), make_computer("Cara")
    a.prospects.create(OrganizationDraft("Studio"))
    package = a.sync.export(
        a.folder, recipient_device_id=c.db.device_id, recipient_name="Cara"
    ).path
    preview = b.sync.stage(package.read_bytes(), package.name)
    assert any("prepared for Cara" in w for w in preview.warnings)
