# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

from __future__ import annotations

from tg_sales.errors import DataDirectoryError, TgSalesError


def test_error_carries_message_action_and_detail() -> None:
    error = DataDirectoryError("Cannot write.", action="Choose another folder.", detail="EACCES")
    assert isinstance(error, TgSalesError)
    assert str(error) == "Cannot write."
    assert error.suggested_action == "Choose another folder."
    assert error.detail == "EACCES"
    assert error.display_text() == "Cannot write.\n\nChoose another folder."
