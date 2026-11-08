"""A fake Steam store served through httpx.MockTransport, built from the synthetic fixture."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

import httpx

FIXTURE = Path(__file__).resolve().parents[1] / "fixtures" / "steam" / "store_responses.json"


class FakeSteam:
    def __init__(self) -> None:
        self.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        self.requests: list[httpx.Request] = []
        # Optional per-request override: return a Response to replace normal handling.
        self.override: Callable[[httpx.Request], httpx.Response | None] | None = None
        self.offline = False

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.offline:
            raise httpx.ConnectError("offline", request=request)
        if self.override is not None:
            response = self.override(request)
            if response is not None:
                return response
        path = request.url.path
        params = request.url.params
        if path == "/search/results/":
            if params.get("start") != "0":
                return httpx.Response(200, json={"desc": "", "items": []})
            key = "search_comingsoon" if params.get("filter") == "comingsoon" else "search_released"
            return httpx.Response(200, json=self.data[key])
        if path == "/api/featuredcategories":
            return httpx.Response(200, json=self.data["featured"])
        if path == "/api/appdetails":
            app_id = params.get("appids", "")
            entry = self.data["appdetails"].get(app_id, {"success": False})
            return httpx.Response(200, json={app_id: entry})
        return httpx.Response(404, text="not found")

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handler)

    def details_requests(self) -> list[str]:
        return [
            r.url.params.get("appids", "") for r in self.requests if r.url.path == "/api/appdetails"
        ]
