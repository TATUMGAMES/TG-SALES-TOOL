"""HTTP access for external sources: timeouts, rate limiting, retries, cancellation.

Every request:

* waits for the per-host rate limiter (one request per ``min_interval``);
* has a timeout and identifies tg_sales in its User-Agent;
* is retried with exponential backoff and jitter on network errors, HTTP 429
  and 5xx responses, honoring ``Retry-After``;
* is never retried after 401/403 (access is not permitted — tg_sales does not
  try to get around it);
* can be cancelled between attempts and during waits.

Failures surface as :class:`SourceError` subclasses with user-facing
messages and suggested actions.
"""

from __future__ import annotations

import random
import threading
import time
from collections.abc import Callable, Mapping
from typing import Any
from urllib.parse import urlsplit

import httpx

from tg_sales import __version__
from tg_sales.cancellation import CancelToken
from tg_sales.errors import TgSalesError

USER_AGENT = f"tg_sales/{__version__} (desktop sales CRM; low-rate, cached requests)"
DEFAULT_TIMEOUT = 15.0
MAX_RETRY_AFTER = 60.0
MAX_BODY_BYTES = 2 * 1024 * 1024

Sleep = Callable[[float], None]


class SourceError(TgSalesError):
    """An external source could not provide data."""


class SourceUnavailableError(SourceError):
    """Network failure, timeout or no connection."""


class AccessDeniedError(SourceError):
    """The source refused access (401/403); tg_sales does not retry or work around it."""


class RateLimitedError(SourceError):
    """The source kept asking us to slow down (429)."""


class UnexpectedResponseError(SourceError):
    """The source answered with an error or data tg_sales does not understand."""


class RateLimiter:
    """Allows one request per host every ``min_interval`` seconds (thread-safe)."""

    def __init__(
        self,
        min_interval: float,
        sleep: Sleep = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._interval = min_interval
        self._sleep = sleep
        self._clock = clock
        self._lock = threading.Lock()
        self._next: dict[str, float] = {}

    def wait(self, host: str, token: CancelToken | None = None) -> None:
        with self._lock:
            now = self._clock()
            start = max(now, self._next.get(host, now))
            self._next[host] = start + self._interval
            delay = start - now
        _cancellable_sleep(delay, self._sleep, token)


def _cancellable_sleep(seconds: float, sleep: Sleep, token: CancelToken | None) -> None:
    remaining = seconds
    while remaining > 0:
        if token is not None:
            token.raise_if_cancelled()
        step = min(remaining, 0.25)
        sleep(step)
        remaining -= step
    if token is not None:
        token.raise_if_cancelled()


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if value is None:
        return None
    try:
        return min(MAX_RETRY_AFTER, max(0.0, float(value)))
    except ValueError:
        return None


class HttpClient:
    def __init__(
        self,
        *,
        transport: httpx.BaseTransport | None = None,
        min_interval: float = 1.5,
        max_retries: int = 3,
        timeout: float = DEFAULT_TIMEOUT,
        sleep: Sleep = time.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._client = httpx.Client(
            transport=transport,
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": USER_AGENT, "Accept-Language": "en"},
        )
        self._limiter = RateLimiter(min_interval, sleep)
        self._max_retries = max_retries
        self._sleep = sleep
        self._jitter = jitter

    def close(self) -> None:
        self._client.close()

    def get(
        self,
        url: str,
        params: Mapping[str, Any] | None = None,
        token: CancelToken | None = None,
        *,
        allow_status: tuple[int, ...] = (),
    ) -> httpx.Response:
        """GET with rate limiting and retries; returns 2xx responses (or ``allow_status``)."""
        host = urlsplit(url).hostname or url
        last_error = ""
        for attempt in range(self._max_retries + 1):
            self._limiter.wait(host, token)
            try:
                response = self._client.get(url, params=dict(params or {}))
            except httpx.TransportError as exc:
                last_error = repr(exc)
                if attempt == self._max_retries:
                    raise SourceUnavailableError(
                        f"Could not reach {host}.",
                        action="Check your internet connection and try again later.",
                        detail=last_error,
                    ) from exc
                self._backoff(attempt, None, token)
                continue
            status = response.status_code
            if 200 <= status < 300 or status in allow_status:
                if len(response.content) > MAX_BODY_BYTES:
                    raise UnexpectedResponseError(
                        f"{host} sent more data than expected.",
                        action="Try again later.",
                        detail=f"{len(response.content)} bytes",
                    )
                return response
            if status in (401, 403):
                raise AccessDeniedError(
                    f"{host} did not allow access (HTTP {status}).",
                    action="tg_sales does not work around access restrictions. Try again later, "
                    "or add games by pasting their store links.",
                    detail=url,
                )
            if status == 429 or status >= 500:
                last_error = f"HTTP {status}"
                if attempt == self._max_retries:
                    if status == 429:
                        raise RateLimitedError(
                            f"{host} asked tg_sales to slow down.",
                            action="Wait a few minutes before searching again.",
                            detail=url,
                        )
                    raise UnexpectedResponseError(
                        f"{host} is having problems (HTTP {status}).",
                        action="Try again later.",
                        detail=url,
                    )
                self._backoff(attempt, _retry_after(response), token)
                continue
            raise UnexpectedResponseError(
                f"{host} answered with HTTP {status}.",
                action="Try again later. If it keeps happening, the source may have changed.",
                detail=url,
            )
        raise SourceUnavailableError(  # pragma: no cover - loop always returns or raises
            f"Could not reach {host}.", action="Try again later.", detail=last_error
        )

    def get_json(
        self, url: str, params: Mapping[str, Any] | None = None, token: CancelToken | None = None
    ) -> Any:
        response = self.get(url, params, token)
        try:
            return response.json()
        except ValueError as exc:
            raise UnexpectedResponseError(
                f"{urlsplit(url).hostname} sent data tg_sales could not read.",
                action="Try again later. If it keeps happening, the source may have changed.",
                detail=repr(exc),
            ) from exc

    def _backoff(self, attempt: int, retry_after: float | None, token: CancelToken | None) -> None:
        delay = retry_after if retry_after is not None else (2**attempt) + self._jitter() * 0.5
        _cancellable_sleep(delay, self._sleep, token)
