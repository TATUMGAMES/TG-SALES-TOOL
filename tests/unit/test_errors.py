from __future__ import annotations

from tg_sales.errors import DataDirectoryError, TgSalesError


def test_error_carries_message_action_and_detail() -> None:
    error = DataDirectoryError("Cannot write.", action="Choose another folder.", detail="EACCES")
    assert isinstance(error, TgSalesError)
    assert str(error) == "Cannot write."
    assert error.suggested_action == "Choose another folder."
    assert error.detail == "EACCES"
    assert error.display_text() == "Cannot write.\n\nChoose another folder."
