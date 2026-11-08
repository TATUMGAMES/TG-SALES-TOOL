"""Every API area exercised end to end against PostgreSQL (no mocks below the HTTP layer)."""

from __future__ import annotations

import io
import json
from collections.abc import Callable
from pathlib import Path

import pytest
from PIL import Image
from tests.api.conftest import HEADERS, Api
from tests.integration.conftest import FakeClock
from tests.integration.test_legacy_transfer import build_history, write_legacy_copy

from tg_sales.db.database import Database
from tg_sales.domain.prospects import OrganizationDraft
from tg_sales.domain.stages import DEFAULT_STAGES
from tg_sales.services.identity import ensure_local_actor
from tg_sales.services.prospects import ProspectService
from tg_sales.sync.engine import SyncService

pytestmark = pytest.mark.integration

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "imports"
STAGE = {s.key: s.id for s in DEFAULT_STAGES}


def _png(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (167, 135, 189)).save(buffer, format="PNG")
    return buffer.getvalue()


def _prospect(api: Api, name: str = "Example Studio", **extra: object) -> str:
    body = {"organization": {"name": name, **extra}, "contacts": []}
    return str(api.post("/prospects", body, expect=201)["id"])


def test_info_settings_and_identity(api: Api) -> None:
    info = api.get("/system/info")
    assert info["first_run"] is True
    assert info["backups_available"] is True
    assert (
        api.call("PUT", "/me", json={"display_name": "  Sam   Seller "})["display_name"]
        == "Sam Seller"
    )
    assert api.get("/system/info")["first_run"] is False
    updated = api.call("PATCH", "/settings", json={"theme": "dark", "backup_keep_latest": 5})
    assert updated["theme"] == "dark" and updated["backup_keep_latest"] == 5
    bad = api.call("PATCH", "/settings", expect=400, json={"time_zone": "Mars/Base"})
    assert "not valid" in bad["error"]["message"]
    assert api.get("/health")["status"] == "ok"
    assert api.post("/system/integrity")["ok"] is True


def test_prospect_lifecycle(api: Api) -> None:
    org = api.post(
        "/prospects",
        {
            "organization": {
                "name": "Pixel Forge",
                "website": "pixelforge.example",
                "tags": ["indie"],
            },
            "contacts": [
                {"name": "Ana", "email": "ana@pixelforge.example", "status": "not_contacted"}
            ],
        },
        expect=201,
    )["id"]
    duplicate = api.post(
        "/prospects",
        {"organization": {"name": "Pixel Forge Studios", "website": "https://pixelforge.example"}},
        expect=409,
    )
    assert "similar prospect" in duplicate["error"]["message"]
    candidates = api.post(
        "/prospects/duplicates", {"organization": {"name": "x", "website": "pixelforge.example"}}
    )
    assert candidates[0]["id"] == org
    api.post(
        "/prospects",
        {
            "organization": {"name": "Pixel Forge Studios", "website": "pixelforge.example"},
            "allow_duplicate": True,
        },
        expect=201,
    )

    detail = api.get(f"/prospects/{org}")
    assert detail["contacts"][0]["email"] == "ana@pixelforge.example"
    contact = detail["contacts"][0]["id"]
    api.call(
        "PUT",
        f"/prospects/{org}",
        json={"name": "Pixel Forge", "website": "pixelforge.example", "country": "Spain"},
    )
    api.post(f"/prospects/{org}/notes", {"text": "Met at GDC"})
    api.post(
        f"/prospects/{org}/contacts", {"name": "Bo", "email": "bo@pixelforge.example"}, expect=201
    )
    api.call(
        "PUT",
        f"/contacts/{contact}",
        json={"name": "Ana Ruiz", "email": "ana@pixelforge.example", "role_title": "Producer"},
    )
    api.post(f"/contacts/{contact}/archive", {"archived": True})
    api.post(
        f"/prospects/{org}/games",
        {
            "title": "Sky Rails",
            "platform": "PC",
            "release_date": "2027-03-14",
            "release_precision": "day",
        },
        expect=201,
    )
    detail = api.get(f"/prospects/{org}")
    assert detail["country"] == "Spain"
    assert {c["name"] for c in detail["contacts"]} >= {"Ana Ruiz", "Bo"}
    assert detail["games"][0]["title"] == "Sky Rails"
    assert any("GDC" in (t.get("summary") or "") for t in detail["timeline"])

    found = api.get("/prospects", params={"text": "sky rails"})
    assert found["total"] == 1 and found["rows"][0]["id"] == org
    assert (
        api.post("/prospects/bulk", {"ids": [org], "action": "add_tag", "tag": "vip"})["count"] == 1
    )
    assert "vip" in api.get("/prospects/tags")
    assert api.get("/prospects", params={"tag": "vip"})["total"] == 1
    api.post("/prospects/bulk", {"ids": [org], "action": "archive"})
    assert api.get("/prospects", params={"text": "pixel forge"})["total"] == 1
    assert (
        api.get("/prospects", params={"text": "pixel forge", "include_archived": True})["total"]
        == 2
    )

    response = api.client.post("/api/prospects/export", headers=HEADERS, json={"ids": [org]})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "Pixel Forge" in response.content.decode("utf-8-sig")

    paged = api.get("/prospects", params={"include_archived": True, "limit": 1, "offset": 1})
    assert len(paged["rows"]) == 1 and paged["total"] == 2


def test_import_wizard_flow_and_undo(api: Api) -> None:
    fields = api.get("/imports/fields")
    assert any(f["field"] == "organization_name" for f in fields)
    with (FIXTURES / "messy_prospects.csv").open("rb") as handle:
        upload = api.call(
            "POST", "/imports/upload", files={"file": ("messy prospects.csv", handle, "text/csv")}
        )
    session = upload["session_id"]
    table = api.run(f"/imports/{session}/read", {})
    assert table["row_count"] >= 4 and table["reliable"]
    mappings = [{"column": m["column"], "field": m["field"]} for m in table["suggestions"]]
    planned = api.run(f"/imports/{session}/plan", {"mappings": mappings, "date_order": "auto"})
    assert planned["groups"]
    if planned["unresolved"]:
        api.post(f"/imports/{session}/decisions", {"all_unresolved": "create"})
    preview = api.run(f"/imports/{session}/preview")
    assert preview["committed"] is False
    created = preview["counts"]["organizations_created"]
    assert created >= 2
    assert api.get("/prospects")["total"] == 0  # preview saved nothing
    problems = api.client.get(f"/api/imports/{session}/problems.csv")
    assert problems.status_code == 200
    result = api.run(f"/imports/{session}/commit")
    assert result["committed"] and result["backup"].startswith("tg_sales_backup_")
    assert api.get("/prospects")["total"] == created
    # Contacted flags come from the file, never from the presence of an email.
    history = api.get("/imports/history")
    assert history[0]["status"] == "committed"
    undo = api.post(f"/imports/history/{history[0]['id']}/undo")
    assert undo["reverted"] >= 1
    assert api.get("/prospects")["total"] == 0
    gone = api.call("POST", f"/imports/{session}/read", expect=400, json={})
    assert "expired" in gone["error"]["message"]


def test_import_refuses_unsupported_files(api: Api) -> None:
    error = api.call(
        "POST",
        "/imports/upload",
        expect=400,
        files={"file": ("macro.exe", b"MZ", "application/octet-stream")},
    )
    assert "cannot be imported" in error["error"]["message"]
    error = api.call(
        "POST",
        "/imports/upload",
        expect=400,
        files={"file": ("old.xls", b"\xd0\xcf\x11\xe0" + b"0" * 100, "application/vnd.ms-excel")},
    )
    assert ".xlsx" in error["error"]["action"]


def test_pipeline_flow(api: Api) -> None:
    org = _prospect(api, "Deal Studio")
    meta = api.get("/pipeline/meta")
    assert {lane["value"] for lane in meta["lanes"]} == {
        "data_licensing",
        "publisher_partnership",
        "mikros_marketing",
    }
    opp = api.post(
        "/opportunities",
        {
            "organization_id": org,
            "product_lane": "data_licensing",
            "stage_id": STAGE["contacted"],
            "title": "Player data",
            "estimated_value": 25000,
            "currency": "usd",
        },
        expect=201,
    )["id"]
    second = api.post(
        "/opportunities",
        {
            "organization_id": org,
            "product_lane": "mikros_marketing",
            "stage_id": STAGE["discovered"],
        },
        expect=201,
    )["id"]
    board = api.get("/pipeline/board")
    cards = board["cards"]
    assert {c["id"] for c in cards} >= {opp, second}
    assert api.get("/pipeline/board", params={"lane": "mikros_marketing"})

    api.post(
        f"/opportunities/{opp}/activities", {"type": "email", "note": "Intro sent"}, expect=201
    )
    api.post(f"/opportunities/{opp}/notes", {"text": "Wants a sample"})
    task = api.post(
        f"/opportunities/{opp}/tasks",
        {"title": "Send sample data", "due_at": "2026-10-19T09:00:00Z"},
        expect=201,
    )["id"]
    reminders = api.get("/reminders")
    assert any(
        r.get("title") == "Send sample data" or "sample" in json.dumps(r).lower() for r in reminders
    )
    api.post(f"/tasks/{task}/done", {"done": True})

    refused = api.post(f"/opportunities/{opp}/move", {"stage_id": STAGE["won"]}, expect=400)
    assert "reason" in refused["error"]["message"].lower()
    api.post(f"/opportunities/{opp}/move", {"stage_id": STAGE["interested"]})
    api.post(
        f"/opportunities/{opp}/move",
        {"stage_id": STAGE["won"], "reason_code": "signed", "reason_note": "Signed"},
    )
    detail = api.get(f"/opportunities/{opp}")
    assert detail["stage"]["id"] == STAGE["won"]
    assert detail["currency"] == "USD"
    email = next(a for a in detail["activities"] if a["type"] == "email")
    api.post(f"/activities/{email['id']}/void", {"reason": "Logged twice"})
    api.call("PUT", f"/opportunities/{opp}", json={"title": "Player data v2", "probability": 0.5})
    assert api.get(f"/opportunities/{opp}")["card"]["title"] == "Player data v2"

    rendered = api.post(
        f"/opportunities/{opp}/handoff/render",
        {"recipient": "lead@example.com", "proposed_dataset": "Retention cohorts"},
    )
    assert "Retention cohorts" in rendered["body"] and rendered["subject"].startswith(
        "Technical handoff"
    )
    assert "Intended use case" in rendered["missing"]
    api.post(f"/opportunities/{opp}/handoff", {"recipient": "lead@example.com"}, expect=201)

    stage = api.post("/pipeline/stages", {"name": "Pilot"}, expect=201)["id"]
    api.call("PATCH", f"/pipeline/stages/{stage}", json={"name": "Paid pilot"})
    stages = api.get("/pipeline/stages")
    assert any(s["name"] == "Paid pilot" for s in stages)
    api.call(
        "PUT", "/pipeline/stages/order", json={"stage_ids": [s["id"] for s in reversed(stages)]}
    )
    api.post(f"/opportunities/{second}/move", {"stage_id": stage})
    assert (
        api.post(f"/pipeline/stages/{stage}/archive", {"move_to_stage_id": STAGE["contacted"]})[
            "count"
        ]
        == 1
    )
    assert api.post(f"/pipeline/stages/{stage}/restore")["ok"]
    assert api.get("/pipeline/organizations", params={"text": "deal"})[0]["id"] == org
    assert api.get("/pipeline/actors")


def test_dashboard_matches_activity(api: Api) -> None:
    org = _prospect(api, "Metric Studio")
    opp = api.post(
        "/opportunities",
        {
            "organization_id": org,
            "product_lane": "publisher_partnership",
            "stage_id": STAGE["contacted"],
        },
        expect=201,
    )["id"]
    api.post(f"/opportunities/{opp}/activities", {"type": "email"}, expect=201)
    periods = api.get("/periods")
    assert {p["preset"] for p in periods} >= {"7d", "30d", "1m", "3m", "6m", "12m"}
    data = api.get("/dashboard", params={"preset": "7d"})
    assert data["period"]["label"] == "Last 7 days"
    metrics = data["data"]["report"]["metrics"]
    assert metrics["leads_added"]["value"] == 1
    custom = api.get(
        "/dashboard",
        params={
            "preset": "custom",
            "start": "2026-10-01",
            "end": "2026-10-31",
            "lane": "publisher_partnership",
        },
    )
    assert custom["period"]["start"] == "2026-10-01"
    error = api.call("GET", "/dashboard", expect=400, params={"preset": "custom"})
    assert "start" in error["error"]["message"]
    assert api.get("/dashboard/salespeople")


def test_discovery_flow(api: Api) -> None:
    meta = api.get("/discovery/meta")
    assert meta["upcoming_days"] == 90 and meta["recent_days"] == 150
    outcome = api.run("/discovery/run", {"max_candidates": 20})
    assert outcome["found"] > 0
    assert api.get("/discovery/last-run")["status"]
    leads = api.post(
        "/discovery/leads/search",
        {"filters": {"timings": ["upcoming", "recent", "unknown_date"], "statuses": ["new"]}},
    )
    assert leads
    lead = leads[0]
    assert lead["candidate"]["title"]
    api.get(f"/discovery/leads/{lead['id']}/duplicates")
    saved = api.post(f"/discovery/leads/{lead['id']}/save", {"include_contact": True})
    assert api.get(f"/prospects/{saved['id']}")["name"]
    again = api.post(
        "/discovery/leads/search",
        {
            "filters": {
                "statuses": ["saved"],
                "timings": ["upcoming", "recent", "unknown_date", "outside"],
            }
        },
    )
    assert any(item["id"] == lead["id"] for item in again)
    if len(leads) > 1:
        api.post(f"/discovery/leads/{leads[1]['id']}/status", {"status": "dismissed"})


def test_discovery_offline_is_a_clear_failure(api: Api, fake_steam) -> None:  # type: ignore[no-untyped-def]
    fake_steam.offline = True
    job = api.wait(api.post("/discovery/run", {}))
    result = job["result"] or {}
    assert job["status"] == "failed" or result.get("error")


def test_playbook_flow(api: Api) -> None:
    meta = api.get("/playbook/meta")
    assert meta["linkedin_note_limit"] == 300
    template = api.post(
        "/playbook/templates",
        {
            "title": "Intro",
            "body": "Hi {contact_name}, congrats on {game_title} at {studio_name}!",
            "channel": "email",
            "tags": ["intro"],
        },
        expect=201,
    )["id"]
    org = api.post(
        "/prospects",
        {"organization": {"name": "Owl Games"}, "contacts": [{"name": "Chloé"}]},
        expect=201,
    )["id"]
    api.post(f"/prospects/{org}/games", {"title": "Owl Quest"}, expect=201)
    preview = api.post(f"/playbook/templates/{template}/preview", {"organization_id": org})
    assert preview["text"] == "Hi Chloé, congrats on Owl Quest at Owl Games!"
    assert preview["complete"]
    blank = api.post(f"/playbook/templates/{template}/preview", {})
    assert not blank["complete"] and blank["warning"]

    detail = api.get(f"/playbook/templates/{template}")
    api.call(
        "PUT",
        f"/playbook/templates/{template}",
        json={
            "title": "Intro v2",
            "body": "Hello {studio_name}",
            "channel": "email",
            "expected_revision": detail["summary"]["revision"],
        },
    )
    stale = api.call(
        "PUT",
        f"/playbook/templates/{template}",
        expect=409,
        json={
            "title": "Old",
            "body": "x",
            "channel": "email",
            "expected_revision": detail["summary"]["revision"],
        },
    )
    assert "changed since you opened" in stale["error"]["message"]
    api.post(f"/playbook/templates/{template}/approved", {"value": True})
    api.post(f"/playbook/templates/{template}/favorite", {"value": True})
    api.post(f"/playbook/templates/{template}/restore", {"revision": 1})
    assert api.get(f"/playbook/templates/{template}")["summary"]["body"].startswith(
        "Hi {contact_name}"
    )
    copy = api.post(f"/playbook/templates/{template}/duplicate", expect=201)["id"]
    api.post(f"/playbook/templates/{copy}/archived", {"value": True})
    api.post(
        f"/playbook/templates/{template}/outcomes",
        {"outcome": "reply", "note": "Quick yes"},
        expect=201,
    )
    assert api.post("/playbook/examples")["count"] > 0
    assert api.post("/playbook/examples")["count"] == 0  # idempotent
    listed = api.get("/playbook/templates", params={"text": "intro"})
    assert any(t["id"] == template for t in listed)
    assert any(t["id"] == copy for t in api.get("/playbook/templates", params={"archived": True}))


def test_reports_and_snapshots(api: Api) -> None:
    org = _prospect(api, "Report Studio")
    api.post(
        "/opportunities",
        {"organization_id": org, "product_lane": "data_licensing", "stage_id": STAGE["contacted"]},
        expect=201,
    )
    result = api.run("/reports", {"preset": "3m", "include_html": True})
    reports = api.get("/reports")
    assert reports[0]["id"] == result["report_id"] and reports[0]["has_pdf"]
    report = result["report_id"]
    pdf = api.client.get(f"/api/reports/{report}/pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF")
    html = api.client.get(f"/api/reports/{report}/html")
    assert html.status_code == 200 and "sandbox" in html.headers["content-security-policy"]
    csv_name = reports[0]["csv_files"][0]
    assert api.client.get(f"/api/reports/{report}/csv/{csv_name}").status_code == 200
    assert api.client.get(f"/api/reports/{report}/csv/..%2F..%2Fsecret.csv").status_code in {
        400,
        404,
    }
    zipped = api.client.get(f"/api/reports/{report}/download")
    assert zipped.content.startswith(b"PK")
    api.call("DELETE", f"/reports/{report}")
    assert api.get("/reports") == []

    snapshot = api.call(
        "POST",
        "/snapshots",
        expect=201,
        files={"image": ("dashboard.png", _png(), "image/png")},
        data={"filters": json.dumps({"period": "Last 7 days", "area": "whole"})},
    )
    assert snapshot["file_name"].startswith("dashboard_snapshot_") and snapshot["width"] == 40
    assert api.get("/snapshots")[0]["id"] == snapshot["id"]
    image = api.client.get(f"/api/snapshots/{snapshot['id']}/image")
    assert image.content.startswith(b"\x89PNG")
    bad = api.call(
        "POST",
        "/snapshots",
        expect=400,
        files={"image": ("x.png", b"<svg onload=alert(1)>", "image/png")},
    )
    assert "not a readable image" in bad["error"]["message"]
    api.call("DELETE", f"/snapshots/{snapshot['id']}")
    assert api.get("/snapshots") == []


def test_sync_export_and_import(
    api: Api, make_database: Callable[..., Database], clock: FakeClock, tmp_path: Path
) -> None:
    _prospect(api, "Local Studio")
    exported = api.run("/sync/export", {"full": True, "passphrase": "a long shared secret"})
    package = api.client.get(f"/api/sync/exports/{exported['file_name']}")
    assert package.status_code == 200 and package.content.startswith(b"PK")
    assert api.client.get("/api/sync/exports/..%2Fsecrets.zip").status_code in {400, 404}

    other = make_database(clock)
    actor = ensure_local_actor(other)
    ProspectService(other, actor).create(OrganizationDraft("Colleague Studio"))
    colleague = SyncService(other, actor, lambda: "Colleague", staging_dir=tmp_path / "staging")
    their = colleague.export(tmp_path / "out")
    preview = api.call(
        "POST",
        "/sync/import",
        files={"package": (their.file_name, their.path.read_bytes(), "application/zip")},
    )
    assert preview["counts"].get("insert", 0) >= 1 and preview["source_actor_name"] == "Colleague"
    result = api.run(f"/sync/import/{preview['token']}/apply", {"resolutions": {}})
    assert result["backup"]
    names = {row["name"] for row in api.get("/prospects")["rows"]}
    assert names == {"Local Studio", "Colleague Studio"}
    info = api.get("/sync")
    assert {e["kind"] for e in info["history"]} == {"export", "import"}

    # Our encrypted package imports on the colleague's computer.
    staged = colleague.stage(package.content, exported["file_name"], "a long shared secret")
    colleague.apply(staged.token)


def test_backups_and_restore(api: Api) -> None:
    _prospect(api, "Before Backup")
    created = api.run("/backups")
    listing = api.get("/backups")
    assert listing["available"] and listing["restore_available"]
    name = created["name"]
    assert api.post(f"/backups/{name}/verify")["verified"]
    download = api.client.get(f"/api/backups/{name}/download")
    assert download.status_code == 200 and download.content.startswith(b"PGDMP")
    _prospect(api, "After Backup")
    refused = api.post(f"/backups/{name}/restore", {"confirm": "yes"}, expect=400)
    assert "RESTORE" in refused["error"]["action"]
    api.run(f"/backups/{name}/restore", {"confirm": "RESTORE"})
    names = {row["name"] for row in api.get("/prospects")["rows"]}
    assert names == {"Before Backup"}
    assert api.get("/health")["status"] == "ok"
    assert api.client.post("/api/backups/..%2F..%2Fx.dump/verify", headers=HEADERS).status_code in {
        400,
        404,
    }
    assert api.call("POST", "/backups/tg_sales_backup_x.dump/verify", expect=400)


def test_resources_and_logo(api: Api) -> None:
    link = api.post(
        "/resources",
        {"title": "Data room", "kind": "link", "target": "dataroom.example/folder"},
        expect=201,
    )["id"]
    folder = api.post(
        "/resources", {"title": "Decks", "kind": "folder", "target": "C:\\Sales\\Decks"}, expect=201
    )["id"]
    unsafe = api.post(
        "/resources", {"title": "Bad", "kind": "link", "target": "javascript:alert(1)"}, expect=400
    )
    assert "safely" in unsafe["error"]["message"]
    items = api.get("/resources")
    assert items[0]["target"] == "https://dataroom.example/folder"
    api.call("PUT", "/resources/order", json={"ids": [folder, link]})
    assert [i["id"] for i in api.get("/resources")] == [folder, link]
    api.call(
        "PUT",
        f"/resources/{link}",
        json={"title": "Data room 2026", "kind": "link", "target": "https://dataroom.example"},
    )
    api.call("DELETE", f"/resources/{folder}")
    assert len(api.get("/resources")) == 1
    refused = api.post(f"/resources/{link}/open", expect=400)
    assert refused["error"]["code"]

    assert api.client.get("/api/branding/logo").status_code == 204
    api.call("PUT", "/branding/logo", files={"image": ("logo.png", _png(2000, 1000), "image/png")})
    logo = api.client.get("/api/branding/logo")
    assert logo.status_code == 200
    with Image.open(io.BytesIO(logo.content)) as stored:
        assert max(stored.size) == 512  # downscaled and re-encoded
    bad = api.call(
        "PUT",
        "/branding/logo",
        expect=400,
        files={"image": ("logo.svg", b"<svg/>", "image/svg+xml")},
    )
    assert "Choose a different image" in bad["error"]["action"]
    api.call("DELETE", "/branding/logo")
    assert api.get("/branding/logo/info")["present"] is False


def test_desktop_database_transfer(
    api: Api, make_database: Callable[..., Database], clock: FakeClock, tmp_path: Path
) -> None:
    original = make_database(clock)
    build_history(original, clock)
    legacy = write_legacy_copy(original, tmp_path / "desktop" / "tg_sales.db")
    dry = api.run(
        "/legacy/transfer",
        files={"database": ("tg_sales.db", legacy.read_bytes())},
        data={"dry_run": "true"},
    )
    assert dry["dry_run"] and api.get("/prospects")["total"] == 0
    result = api.run("/legacy/transfer", files={"database": ("tg_sales.db", legacy.read_bytes())})
    assert result["ok"], result
    assert result["adopted_device_id"] == original.device_id
    assert api.get("/prospects")["total"] == 6
    assert api.get("/system/info")["device_id"] == original.device_id
