"""The KPI dictionary and the implementation must describe the same metrics."""

from __future__ import annotations

import re
from pathlib import Path

from tg_sales.domain.kpi import METRIC_LABELS

DOC = Path(__file__).resolve().parents[2] / "docs" / "KPI_DICTIONARY.md"


def metric_sections() -> dict[str, str]:
    text = DOC.read_text(encoding="utf-8")
    metrics_part = text.split("## 2. Metrics", 1)[1]
    parts = re.split(r"^### (.+?)\s*$", metrics_part, flags=re.MULTILINE)
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def words(text: str) -> set[str]:
    return set(re.findall(r"[a-z][a-z-]*", text.casefold()))


def test_every_dictionary_metric_is_implemented() -> None:
    not_implemented = [
        heading
        for heading, body in metric_sections().items()
        if "**Status:** Implemented" not in body
    ]
    assert not_implemented == []


def test_every_dashboard_metric_is_defined_in_the_dictionary() -> None:
    headings = [words(h) for h in metric_sections()]
    undefined = [
        label for label in METRIC_LABELS.values() if not any(words(label) <= h for h in headings)
    ]
    assert undefined == []
