# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""HTTP security for a CRM that runs on the user's computer.

* **Host check** (DNS-rebinding protection): requests must address the server
  as ``127.0.0.1``/``localhost`` (plus configured hosts).
* **Cross-site request protection**: state-changing API requests must carry
  the ``X-TG-Sales: 1`` header. Browsers only let pages on another site send
  custom headers after a CORS preflight, which is refused for unknown origins,
  so a malicious web page cannot make the user's browser change CRM data.
  ``Origin``, when present, must be an allowed origin.
* **Security headers**: a strict Content-Security-Policy (no inline scripts,
  no third-party content), no framing, no MIME sniffing, no referrer leakage,
  and ``Cache-Control: no-store`` for API responses (private data is never
  cached by the browser or a proxy).
* **Error envelope**: expected errors return ``{"error": {"message",
  "action", "code"}}``; unexpected ones are logged and return a safe message
  without internal details.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from tg_sales.errors import ConflictError, TgSalesError

__all__ = ["ConflictError", "NotFoundError", "SecurityMiddleware", "install_error_handlers"]

logger = logging.getLogger(__name__)

CSRF_HEADER = "x-tg-sales"
SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; font-src 'self' data:; connect-src 'self'; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'; "
    "worker-src 'self'; manifest-src 'self'"
)


class NotFoundError(TgSalesError):
    """The requested record does not exist (or no longer exists)."""

    def __init__(self, what: str = "That record") -> None:
        super().__init__(f"{what} no longer exists.", action="Refresh the page and try again.")


def error_body(message: str, action: str, code: str) -> dict[str, dict[str, str]]:
    return {"error": {"message": message, "action": action, "code": code}}


class SecurityMiddleware(BaseHTTPMiddleware):
    def __init__(self, app: object, *, allowed_hosts: set[str], allowed_origins: set[str]) -> None:
        super().__init__(app)  # type: ignore[arg-type]
        self._hosts = allowed_hosts
        self._origins = allowed_origins

    async def dispatch(
        self, request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        host = (request.headers.get("host") or "").rsplit(":", 1)[0].strip("[]").lower()
        if host not in self._hosts:
            return JSONResponse(
                error_body(
                    "This address is not allowed.",
                    "Open tg_sales at http://127.0.0.1 as shown by launch.bat.",
                    "bad_host",
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )
        is_api = request.url.path.startswith("/api/")
        if is_api and request.method not in SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in self._origins:
                return JSONResponse(
                    error_body(
                        "Request refused.", "Use tg_sales in its own browser tab.", "bad_origin"
                    ),
                    status_code=status.HTTP_403_FORBIDDEN,
                )
            if request.headers.get(CSRF_HEADER) != "1":
                return JSONResponse(
                    error_body("Request refused.", "Reload the page and try again.", "csrf"),
                    status_code=status.HTTP_403_FORBIDDEN,
                )
        response = await call_next(request)
        response.headers.setdefault("Content-Security-Policy", CSP)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=()"
        )
        if is_api:
            response.headers["Cache-Control"] = "no-store"
        return response


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(TgSalesError)
    async def _expected(_request: Request, exc: TgSalesError) -> JSONResponse:
        code = type(exc).__name__.removesuffix("Error").lower() or "error"
        status_code = status.HTTP_400_BAD_REQUEST
        if isinstance(exc, NotFoundError):
            status_code = status.HTTP_404_NOT_FOUND
        elif isinstance(exc, ConflictError):
            status_code = status.HTTP_409_CONFLICT
        if exc.detail:
            logger.info("Request refused", extra={"context": {"code": code, "detail": exc.detail}})
        return JSONResponse(
            error_body(exc.user_message, exc.suggested_action, code), status_code=status_code
        )

    @app.exception_handler(RequestValidationError)
    async def _invalid(_request: Request, exc: RequestValidationError) -> JSONResponse:
        problems = []
        for error in exc.errors()[:5]:
            location = ".".join(str(p) for p in error.get("loc", ()) if p not in ("body", "query"))
            problems.append(
                f"{location}: {error.get('msg', 'invalid')}" if location else error.get("msg", "")
            )
        return JSONResponse(
            {
                **error_body(
                    "Some of the information is not valid.",
                    "Correct the highlighted fields and try again.",
                    "validation",
                ),
                "problems": problems,
            },
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
        message = "Not found." if exc.status_code == 404 else str(exc.detail)
        return JSONResponse(
            error_body(message, "Check the address and try again.", f"http_{exc.status_code}"),
            status_code=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _unexpected(_request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unexpected error while handling a request", exc_info=exc)
        return JSONResponse(
            error_body(
                "Something went wrong.",
                "Try again. If it keeps happening, send the tg_sales log file to your support "
                "contact.",
                "internal",
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
