# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Default pipeline stages shared by every installation.

Default stages have deterministic identifiers so that every computer creates
exactly the same stage records and sync never duplicates them.
"""

from __future__ import annotations

from dataclasses import dataclass

from tg_sales.domain.enums import StageOutcome
from tg_sales.domain.ids import stable_id


@dataclass(frozen=True)
class DefaultStage:
    key: str
    name: str
    sort_order: int
    outcome: StageOutcome

    @property
    def id(self) -> str:
        return stable_id(f"pipeline_stage:{self.key}")


DEFAULT_STAGES: tuple[DefaultStage, ...] = (
    DefaultStage("discovered", "Discovered", 10, StageOutcome.OPEN),
    DefaultStage("researching", "Researching", 20, StageOutcome.OPEN),
    DefaultStage("contacted", "Contacted", 30, StageOutcome.OPEN),
    DefaultStage("follow_up", "Follow-Up", 40, StageOutcome.OPEN),
    DefaultStage("interested", "Interested", 50, StageOutcome.OPEN),
    DefaultStage("technical_review", "Technical Review", 60, StageOutcome.OPEN),
    DefaultStage("negotiation", "Negotiation", 70, StageOutcome.OPEN),
    DefaultStage("won", "Won", 80, StageOutcome.WON),
    DefaultStage("lost", "Lost", 90, StageOutcome.LOST),
    DefaultStage("not_a_fit", "Not a Fit", 100, StageOutcome.NOT_A_FIT),
)
