# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""HTTP security controls of the local server."""

from __future__ import annotations

import pytest
from pydantic import SecretStr
from tests.api.conftest import HEADERS, Api

from tg_sales.api.settings import ConfigurationError, ServerSettings, is_loopback

pytestmark = pytest.mark.integration


def test_state_changes_need_the_anti_forgery_header(api: Api) -> None:
    body = {"organization": {"name": "Forged"}}
    response = api.client.post("/api/prospects", json=body)
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "csrf"
    assert api.client.post("/api/prospects", json=body, headers=HEADERS).status_code == 201


def test_foreign_origin_is_refused(api: Api) -> None:
    response = api.client.post(
        "/api/prospects",
        json={"organization": {"name": "Evil"}},
        headers={**HEADERS, "Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "bad_origin"


def test_dns_rebinding_host_is_refused(api: Api) -> None:
    response = api.client.get("/api/system/info", headers={"Host": "attacker.example"})
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_host"


def test_security_headers_and_no_caching(api: Api) -> None:
    response = api.client.get("/api/prospects")
    assert response.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in response.headers["content-security-policy"]
    assert "frame-ancestors 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["x-frame-options"] == "DENY"
    assert response.headers["referrer-policy"] == "no-referrer"


def test_errors_are_safe_and_actionable(api: Api) -> None:
    missing = api.client.get("/api/prospects/01a17a48-277a-788a-9fed-4844a5398cbc")
    assert missing.status_code == 404
    assert set(missing.json()["error"]) == {"message", "action", "code"}
    unknown = api.client.get("/api/does-not-exist")
    assert unknown.status_code == 404 and unknown.json()["error"]["code"] == "http_404"
    invalid = api.client.post(
        "/api/prospects", json={"organization": {"name": ""}}, headers=HEADERS
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation"
    extra = api.client.post(
        "/api/prospects", json={"organization": {"name": "x", "admin": True}}, headers=HEADERS
    )
    assert extra.status_code == 422  # unknown fields are rejected


def test_sql_injection_text_is_just_text(api: Api) -> None:
    hostile = "x'); DROP TABLE organizations; --"
    api.post("/prospects", {"organization": {"name": hostile}}, expect=201)
    rows = api.get("/prospects", params={"text": "' OR 1=1 --"})["rows"]
    assert rows == []
    assert api.get("/prospects", params={"text": "drop table"})["rows"][0]["name"] == hostile


def test_api_docs_hidden_outside_development(api: Api) -> None:
    assert api.client.get("/api/docs").status_code == 404
    assert api.client.get("/api/openapi.json").status_code == 404


def test_remote_listening_is_refused_without_authentication() -> None:
    assert is_loopback("127.0.0.1") and is_loopback("::1") and is_loopback("localhost")
    assert not is_loopback("0.0.0.0")  # noqa: S104 - checking the refusal
    ServerSettings(host="127.0.0.1", database_url=SecretStr("postgresql://x")).check_safe()
    with pytest.raises(ConfigurationError, match="other computers could reach"):
        ServerSettings(host="0.0.0.0", database_url=SecretStr("postgresql://x")).check_safe()  # noqa: S104
    with pytest.raises(ConfigurationError):
        ServerSettings(host="192.168.1.20", allow_remote=True).check_safe()
