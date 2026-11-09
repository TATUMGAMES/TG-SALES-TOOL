# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""The FastAPI application: API routes under ``/api`` plus the built web app.

The compiled React app (``web/dist``) is served from the same origin, so the
local app needs no separate web server. Unknown non-API paths return
``index.html`` (client-side routing). The service worker and manifest are
served with headers that let the browser update them promptly.
"""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from tg_sales import __version__
from tg_sales.api.context import AppContext
from tg_sales.api.routers import (
    collaboration,
    custom_fields,
    dashboard,
    discovery,
    imports,
    lanes,
    pipeline,
    playbook,
    prospects,
    reports,
    settings,
    system,
)
from tg_sales.api.security import SecurityMiddleware, error_body, install_error_handlers
from tg_sales.api.settings import Environment

DEFAULT_HOSTS = {"127.0.0.1", "localhost", "::1", "testserver"}


def create_app(context: AppContext, *, start_scheduler: bool = False) -> FastAPI:
    server = context.server
    development = server.environment is Environment.DEVELOPMENT

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if start_scheduler:
            context.start_scheduler()
        yield
        context.close()

    app = FastAPI(
        title="TG Sales CRM API",
        version=__version__,
        docs_url="/api/docs" if development else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if development else None,
        lifespan=lifespan,
    )
    app.state.context = context
    install_error_handlers(app)

    origins = set(server.local_origins) | set(server.allowed_origins)
    if development:
        origins |= {"http://127.0.0.1:5173", "http://localhost:5173"}
    app.add_middleware(SecurityMiddleware, allowed_hosts=DEFAULT_HOSTS, allowed_origins=origins)
    if server.allowed_origins or development:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=sorted(origins),
            allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
            allow_headers=["Content-Type", "X-TG-Sales"],
            allow_credentials=False,
        )

    for module in (
        system,
        prospects,
        imports,
        lanes,
        pipeline,
        dashboard,
        discovery,
        playbook,
        reports,
        collaboration,
        settings,
        custom_fields,
    ):
        app.include_router(module.router, prefix="/api")

    @app.api_route(
        "/api/{path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def api_not_found(path: str) -> JSONResponse:
        return JSONResponse(
            error_body("Not found.", "Check the address and try again.", "http_404"),
            status_code=404,
        )

    static = server.static_dir
    if static is not None and (static / "index.html").is_file():
        _mount_spa(app, static)
    return app


# Windows takes file types from the registry, where ".js" is sometimes "text/plain";
# browsers then refuse to run the app. Register the correct types explicitly.
_WEB_TYPES = {
    ".js": "text/javascript",
    ".mjs": "text/javascript",
    ".css": "text/css",
    ".svg": "image/svg+xml",
    ".json": "application/json",
    ".webmanifest": "application/manifest+json",
    ".woff2": "font/woff2",
    ".png": "image/png",
    ".html": "text/html",
}


def register_web_types() -> None:
    for suffix, media_type in _WEB_TYPES.items():
        mimetypes.add_type(media_type, suffix)


def _mount_spa(app: FastAPI, static: Path) -> None:
    register_web_types()
    root = static.resolve()
    index = root / "index.html"
    if (root / "assets").is_dir():
        app.mount("/assets", StaticFiles(directory=root / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            response = FileResponse(candidate)
            if candidate.name in {"sw.js", "manifest.webmanifest", "registerSW.js"}:
                response.headers["Cache-Control"] = "no-cache"
            return response
        response = FileResponse(index, media_type="text/html")
        response.headers["Cache-Control"] = "no-cache"
        return response
