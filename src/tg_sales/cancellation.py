"""Cooperative cancellation for long-running work.

Background operations receive a :class:`CancelToken` and call
:meth:`CancelToken.raise_if_cancelled` at safe points. This module has no web or UI
dependency so services can use it directly.
"""

from __future__ import annotations

import threading


class OperationCancelledError(Exception):
    """Raised inside a background operation when the user cancels it."""


class CancelToken:
    """Thread-safe cancellation flag shared between the UI and a worker."""

    def __init__(self) -> None:
        self._event = threading.Event()

    def cancel(self) -> None:
        self._event.set()

    @property
    def cancelled(self) -> bool:
        return self._event.is_set()

    def raise_if_cancelled(self) -> None:
        if self._event.is_set():
            raise OperationCancelledError
