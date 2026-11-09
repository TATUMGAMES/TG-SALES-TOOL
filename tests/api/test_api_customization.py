# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Customizing an installation through the API: lanes, custom fields, imports and branding."""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from PIL import Image
from tests.api.conftest import Api

from tg_sales.api.context import AppContext
from tg_sales.services.branding import BrandingService, BrandingStore, ImageSlot, sanitize_svg
from tg_sales.services.branding import LogoError as BrandingImageError

SAFE_SVG = (
    b'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">'
    b'<rect width="10" height="10" fill="#6f4f8a"/></svg>'
)


def _png(width: int = 40, height: int = 30) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), (90, 140, 200)).save(buffer, format="PNG")
    return buffer.getvalue()


# -- lanes -------------------------------------------------------------------------


def test_lane_management_through_the_api(api: Api) -> None:
    created = api.post("/lanes", {"name": "Strategic Partnerships", "color": "#8fa8d8"}, expect=201)
    assert created["key"] == "strategic_partnerships"
    assert "strategic_partnerships" in {
        lane["value"] for lane in api.get("/pipeline/meta")["lanes"]
    }

    org = str(api.post("/prospects", {"organization": {"name": "Lane Co"}}, expect=201)["id"])
    stage = api.get("/pipeline/stages")[0]["id"]
    opp = api.post(
        "/opportunities",
        {"organization_id": org, "product_lane": "strategic_partnerships", "stage_id": stage},
        expect=201,
    )["id"]

    api.call("PUT", "/lanes/strategic_partnerships", json={"name": "Alliances"})
    board = api.get("/pipeline/board", params={"lane": "strategic_partnerships"})
    assert [card["id"] for card in board["cards"]] == [opp]
    lanes = {lane["key"]: lane for lane in api.get("/lanes")}
    assert lanes["strategic_partnerships"]["name"] == "Alliances"
    assert lanes["strategic_partnerships"]["opportunity_count"] == 1

    refused = api.call("DELETE", "/lanes/strategic_partnerships", expect=400)
    assert "archive" in refused["error"]["action"]
    moved = api.post("/lanes/strategic_partnerships/move", {"target_key": "partnerships"})
    assert moved["opportunities"] == 1
    api.call("DELETE", "/lanes/strategic_partnerships")
    assert "strategic_partnerships" not in {lane["key"] for lane in api.get("/lanes")}
    assert api.get(f"/opportunities/{opp}")["card"]["product_lane"] == "partnerships"

    archived = api.post("/lanes/other/archive", {"archived": True})
    assert archived["archived"] is True
    assert "other" not in {lane["value"] for lane in api.get("/pipeline/meta")["lanes"]}
    keys = [lane["key"] for lane in api.get("/lanes", params={"include_archived": False})]
    api.call("PUT", "/lanes/order", json={"keys": list(reversed(keys))})
    assert [lane["key"] for lane in api.get("/lanes", params={"include_archived": False})] == list(
        reversed(keys)
    )
    presets = {p["key"] for p in api.get("/lanes/presets")}
    assert presets == {"generic", "tatum_games"}

    # Reports and the dashboard accept any configured lane.
    dashboard = api.get("/dashboard", params={"lane": "partnerships"})
    assert dashboard["data"]
    unknown = api.call(
        "POST",
        "/opportunities",
        expect=400,
        json={
            "organization_id": org,
            "product_lane": "no_such_lane",
            "stage_id": stage,
        },
    )
    assert "does not exist" in unknown["error"]["message"]


# -- custom fields and imports --------------------------------------------------------


def test_custom_fields_in_the_import_wizard_and_record(api: Api, tmp_path: Path) -> None:
    field = api.post(
        "/custom-fields",
        {"label": "Account Tier", "field_type": "text", "record_type": "prospect"},
        expect=201,
    )
    assert field["target"] == "custom:prospect:account_tier"
    import_fields = {f["field"]: f for f in api.get("/imports/fields")}
    assert {"review_date", "qualification_source_url", field["target"]} <= set(import_fields)
    assert import_fields["review_date"]["value_type"] == "date"
    assert import_fields[field["target"]]["custom"] is True

    url = "https://example.com/search?q=studio&page=2#result-4"
    csv = (
        f"Company,Reviewed On,Qualification Source URL,Account Tier,Internal Notes\n"
        f'Tier Co,2026-03-01,"{url}",Gold,Keep\n'
    )
    upload = api.call(
        "POST", "/imports/upload", files={"file": ("tiers.csv", csv.encode(), "text/csv")}
    )
    session = upload["session_id"]
    table = api.run(f"/imports/{session}/read", {})
    suggested = {s["header"]: s["field"] for s in table["suggestions"]}
    assert suggested == {
        "Company": "organization_name",
        "Reviewed On": "review_date",
        "Qualification Source URL": "qualification_source_url",
        "Account Tier": field["target"],
        "Internal Notes": None,  # not recognized: the user decides
    }
    mappings = [{"column": s["column"], "field": s["field"]} for s in table["suggestions"]]
    api.run(f"/imports/{session}/plan", {"mappings": mappings})
    result = api.run(f"/imports/{session}/commit")
    assert result["counts"]["rows_imported"] == 1 and result["counts"]["rows_failed"] == 0

    prospect = api.get("/prospects")["rows"][0]
    detail = api.get(f"/prospects/{prospect['id']}")
    assert detail["reviewed_on"] == "2026-03-01"
    assert detail["qualification_source_url"] == url
    assert detail["custom_fields"] == [
        {"key": "account_tier", "label": "Account Tier", "field_type": "text", "value": "Gold"}
    ]
    # An edit that does not send the new fields keeps them.
    api.call("PUT", f"/prospects/{prospect['id']}", json={"name": "Tier Company"})
    detail = api.get(f"/prospects/{prospect['id']}")
    assert (detail["reviewed_on"], detail["qualification_source_url"]) == ("2026-03-01", url)
    assert detail["custom_fields"][0]["value"] == "Gold"

    bad = api.call(
        "PUT",
        f"/prospects/{prospect['id']}",
        expect=400,
        json={"name": "Tier Company", "custom_fields": {"account_tier": "x" * 10_001}},
    )
    assert "Account Tier" in bad["error"]["message"]

    unknown = api.call(
        "POST",
        f"/imports/{session}/plan",
        expect=400,
        json={"mappings": [{"column": 0, "field": "custom:prospect:nope"}]},
    )
    assert unknown["error"]["message"]


def test_mapping_two_columns_to_one_field_is_refused(api: Api) -> None:
    csv = "Company,Reviewed On,Review Date\nDup Co,2026-01-01,2026-02-02\n"
    upload = api.call(
        "POST", "/imports/upload", files={"file": ("dup.csv", csv.encode(), "text/csv")}
    )
    session = upload["session_id"]
    api.run(f"/imports/{session}/read", {})
    refused = api.call(
        "POST",
        f"/imports/{session}/plan",
        expect=400,
        json={
            "mappings": [
                {"column": 0, "field": "organization_name"},
                {"column": 1, "field": "review_date"},
                {"column": 2, "field": "review_date"},
            ]
        },
    )
    assert "Only one column" in refused["error"]["message"]


# -- branding ---------------------------------------------------------------------------


def test_branding_settings_images_and_reset(api: Api) -> None:
    branding = api.get("/branding")
    assert branding["display_name"] == "Tatum Games"  # the original installation's default
    assert not any(image["present"] for image in branding["images"].values())

    updated = api.call(
        "PATCH",
        "/branding",
        json={"company_name": "  Acme   Consulting ", "accent_color": "#F6D271"},
    )
    assert updated["company_name"] == "Acme Consulting"
    assert (updated["accent_color"], updated["accent_text_color"]) == ("#f6d271", "#1a1320")
    bad = api.call("PATCH", "/branding", expect=400, json={"accent_color": "yellow"})
    assert bad["error"]["message"]

    api.call(
        "PUT", "/branding/images/logo", files={"image": ("l.png", _png(1200, 600), "image/png")}
    )
    api.call(
        "PUT",
        "/branding/images/compact_logo",
        files={"image": ("c.svg", SAFE_SVG, "image/svg+xml")},
    )
    api.call(
        "PUT", "/branding/images/favicon", files={"image": ("f.png", _png(300, 300), "image/png")}
    )
    favicon = api.client.get("/api/branding/images/favicon")
    with Image.open(io.BytesIO(favicon.content)) as image:
        assert image.size == (64, 64)
    compact = api.client.get("/api/branding/images/compact_logo")
    assert compact.headers["content-type"].startswith("image/svg+xml")
    assert "sandbox" in compact.headers["content-security-policy"]
    assert compact.headers["x-content-type-options"] == "nosniff"
    images = api.get("/branding")["images"]
    assert all(image["present"] for image in images.values())
    assert images["compact_logo"]["media_type"] == "image/svg+xml"
    # The original logo endpoint serves the same logo.
    assert (
        api.client.get("/api/branding/logo").content
        == api.client.get("/api/branding/images/logo").content
    )

    reset = api.post("/branding/reset")
    assert reset["display_name"] == "Tatum Games" and reset["accent_color"] is None
    assert not any(image["present"] for image in reset["images"].values())


def test_branding_survives_a_restart(api: Api) -> None:
    api.call("PATCH", "/branding", json={"company_name": "Northwind"})
    api.call("PUT", "/branding/images/logo", files={"image": ("l.png", _png(), "image/png")})
    context: AppContext = api.context
    restarted = BrandingService(context.database, BrandingStore(context.paths.user_assets_dir))
    assert restarted.get().display_name == "Northwind"
    assert restarted.store.read(ImageSlot.LOGO) is not None
    context.reopen()  # what a restore or restart does: settings and files come back
    assert context.services.branding.get().display_name == "Northwind"


@pytest.mark.parametrize(
    "svg",
    [
        b'<svg xmlns="http://www.w3.org/2000/svg"><script>alert(1)</script></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" onload="alert(1)"/>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><foreignObject><p>x</p></foreignObject></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:x="http://www.w3.org/1999/xlink">'
        b'<image x:href="https://evil.example/a.png"/></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><a href="javascript:alert(1)"><rect/></a></svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg"><style>@import url(https://x.example/a.css);</style></svg>',
        b'<!DOCTYPE svg [<!ENTITY a "aaaa">]><svg xmlns="http://www.w3.org/2000/svg">&a;</svg>',
        b'<svg xmlns="http://www.w3.org/2000/svg">'
        b'<set attributeName="href" to="javascript:x"/></svg>',
        b"<html><body>not svg</body></html>",
    ],
)
def test_unsafe_svgs_are_refused(svg: bytes) -> None:
    with pytest.raises(BrandingImageError):
        sanitize_svg(svg)


def test_safe_svg_is_kept_unchanged() -> None:
    with_image = (
        b'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink">'
        b'<defs><linearGradient id="g"/></defs><rect fill="url(#g)" width="4" height="4"/>'
        b'<use xlink:href="#g"/><image href="data:image/png;base64,iVBORw0KGgo="/></svg>'
    )
    assert sanitize_svg(SAFE_SVG) == SAFE_SVG
    assert sanitize_svg(with_image) == with_image
