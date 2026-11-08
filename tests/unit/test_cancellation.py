from __future__ import annotations

import pytest

from tg_sales.cancellation import CancelToken, OperationCancelledError


def test_cancel_token() -> None:
    token = CancelToken()
    assert token.cancelled is False
    token.raise_if_cancelled()
    token.cancel()
    assert token.cancelled is True
    with pytest.raises(OperationCancelledError):
        token.raise_if_cancelled()
