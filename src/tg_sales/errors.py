"""Application error types.

Expected failures that a user can act on are raised as :class:`TgSalesError`
subclasses. Each carries a plain-language message plus a suggested next action
so the UI can always tell the user what to do, while technical detail goes to
the log.
"""

from __future__ import annotations


class TgSalesError(Exception):
    """Base class for expected, user-actionable application errors."""

    def __init__(self, message: str, *, action: str, detail: str | None = None) -> None:
        super().__init__(message)
        self.user_message = message
        self.suggested_action = action
        self.detail = detail

    def display_text(self) -> str:
        """Return the message and suggested action formatted for a dialog."""
        return f"{self.user_message}\n\n{self.suggested_action}"


class ConflictError(TgSalesError):
    """The change conflicts with the current state (e.g. the record was edited elsewhere)."""


class DataDirectoryError(TgSalesError):
    """The application data directory is missing, unwritable, or unsafe."""
