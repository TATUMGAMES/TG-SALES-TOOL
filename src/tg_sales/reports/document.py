# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Report HTML preview and PDF output.

The HTML preview is a self-contained page (charts embedded as SVG). The PDF is
built with ReportLab: A4, 15 mm margins, "Page X of Y" footers, major sections
starting on a new page, charts as vector drawings. Long lists are shortened in
both documents and complete in the CSV files. All text is escaped.
"""

from __future__ import annotations

import base64
import html
import re
from collections.abc import Callable
from pathlib import Path
from typing import Any
from xml.sax.saxutils import escape

from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import (
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)
from reportlab.platypus import Table as PdfTable

from tg_sales.reports.charts import to_drawing, to_svg
from tg_sales.reports.content import PDF_ROW_LIMIT, Chart, ReportContent, Table
from tg_sales.reports.fonts import font_names

NEW_PAGE_SECTIONS = frozenset({"acquisition", "stages", "activity", "trends", "quality"})
PAGE_PATTERN = re.compile(rb"/Type\s*/Page(?![s\w])")
MARGIN = 15 * mm

STYLE = """
body { font-family: 'Segoe UI', Arial, sans-serif; font-size: 10pt; color: #1f2430;
       max-width: 960px; margin: 24px auto; padding: 0 16px; }
h1 { font-size: 20pt; margin-bottom: 2pt; }
h2 { font-size: 14pt; margin-top: 18pt; color: #4b3a63; border-bottom: 2px solid #a787bd; }
h3 { font-size: 11pt; margin-top: 10pt; }
p.muted, p.definition, p.note { color: #5b6070; font-size: 8.5pt; }
table.data { border-collapse: collapse; margin-top: 4pt; width: 100%; }
table.data th { background-color: #ece6f2; text-align: left; }
table.data th, table.data td { border: 1px solid #c9c4d4; padding: 3px 6px; }
td.num { text-align: right; }
.chart svg { max-width: 100%; height: auto; }
"""


def _cell(value: object) -> str:
    if isinstance(value, int | float) and not isinstance(value, bool):
        return f'<td class="num">{value:,}</td>'
    return f"<td>{html.escape(str(value))}</td>"


def _table_html(table: Table) -> str:
    parts = [f"<h3>{html.escape(table.title)}</h3>"]
    if table.definition:
        parts.append(f'<p class="definition">Definition: {html.escape(table.definition)}</p>')
    if not table.rows:
        parts.append(f'<p class="muted">{html.escape(table.empty_text)}</p>')
    else:
        header = "".join(f"<th>{html.escape(c)}</th>" for c in table.columns)
        shown = table.rows[:PDF_ROW_LIMIT]
        body = "".join("<tr>" + "".join(_cell(v) for v in row) + "</tr>" for row in shown)
        parts.append(
            f'<table class="data"><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>'
        )
        hidden = len(table.rows) - len(shown)
        if hidden > 0:
            parts.append(
                f'<p class="note">… and {hidden:,} more rows in {html.escape(table.key)}.csv.</p>'
            )
    if table.note:
        parts.append(f'<p class="note">{html.escape(table.note)}</p>')
    return "\n".join(parts)


def render_html(content: ReportContent, image_src: Callable[[Chart], str]) -> str:
    meta = content.meta
    parts = [
        "<!doctype html><html lang='en'><head><meta charset='utf-8'>",
        "<meta name='viewport' content='width=device-width, initial-scale=1'>",
        f"<title>{html.escape(content.title)} · {html.escape(content.subtitle)}</title>",
        f"<style>{STYLE}</style></head><body>",
        f"<h1>{html.escape(content.title)}</h1>",
        f"<p><b>{html.escape(content.subtitle)}</b></p>",
        f'<p class="muted">{html.escape(meta.filter_text)} · Generated '
        f"{html.escape(meta.local(meta.generated_at))} by tg_sales "
        f"{html.escape(meta.app_version)}</p>",
    ]
    for section in content.sections:
        parts.append(f"<h2>{html.escape(section.title)}</h2>")
        parts.extend(f"<p>{html.escape(p)}</p>" for p in section.paragraphs)
        if section.bullets:
            items = "".join(f"<li>{html.escape(b)}</li>" for b in section.bullets)
            parts.append(f"<ul>{items}</ul>")
        for chart in section.charts:
            parts.append(f"<h3>{html.escape(chart.title)}</h3>")
            parts.append(
                f'<p class="chart"><img src="{html.escape(image_src(chart), quote=True)}" '
                f'alt="{html.escape(chart.title, quote=True)}"></p>'
            )
        parts.extend(_table_html(t) for t in section.tables)
    parts.append("</body></html>")
    return "\n".join(parts)


def chart_data_uri(chart: Chart) -> str:
    encoded = base64.b64encode(to_svg(chart).encode("utf-8")).decode("ascii")
    return f"data:image/svg+xml;base64,{encoded}"


def preview_html(content: ReportContent) -> str:
    """Self-contained HTML for viewing in a browser (charts embedded)."""
    return render_html(content, chart_data_uri)


# ----------------------------------------------------------------------- PDF
def _styles() -> dict[str, ParagraphStyle]:
    regular, bold = font_names()
    base = ParagraphStyle(
        "base", fontName=regular, fontSize=9.5, leading=12.5, textColor=colors.HexColor("#1f2430")
    )
    return {
        "body": base,
        "title": ParagraphStyle("title", parent=base, fontName=bold, fontSize=20, leading=24),
        "subtitle": ParagraphStyle("subtitle", parent=base, fontName=bold, fontSize=11),
        "h2": ParagraphStyle(
            "h2",
            parent=base,
            fontName=bold,
            fontSize=14,
            leading=18,
            spaceBefore=10,
            spaceAfter=4,
            textColor=colors.HexColor("#4b3a63"),
        ),
        "h3": ParagraphStyle(
            "h3", parent=base, fontName=bold, fontSize=10.5, leading=14, spaceBefore=8, spaceAfter=2
        ),
        "muted": ParagraphStyle(
            "muted", parent=base, fontSize=8, leading=10.5, textColor=colors.HexColor("#5b6070")
        ),
        "cell": ParagraphStyle("cell", parent=base, fontSize=8, leading=10),
        "num": ParagraphStyle("num", parent=base, fontSize=8, leading=10, alignment=TA_RIGHT),
        "head": ParagraphStyle("head", parent=base, fontName=bold, fontSize=8, leading=10),
    }


def _p(text: object, style: ParagraphStyle) -> Paragraph:
    return Paragraph(escape(str(text)), style)


def _pdf_table(table: Table, styles: dict[str, ParagraphStyle], width: float) -> list[Any]:
    flow: list[Any] = [_p(table.title, styles["h3"])]
    if table.definition:
        flow.append(_p(f"Definition: {table.definition}", styles["muted"]))
    if not table.rows:
        flow.append(_p(table.empty_text, styles["muted"]))
    else:
        shown = table.rows[:PDF_ROW_LIMIT]
        data = [[_p(c, styles["head"]) for c in table.columns]]
        for row in shown:
            data.append(
                [
                    _p(f"{v:,}", styles["num"])
                    if isinstance(v, int | float) and not isinstance(v, bool)
                    else _p(v, styles["cell"])
                    for v in row
                ]
            )
        pdf_table = PdfTable(
            data, colWidths=[width / len(table.columns)] * len(table.columns), repeatRows=1
        )
        pdf_table.setStyle(
            TableStyle(
                [
                    ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#ece6f2")),
                    ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#c9c4d4")),
                    ("VALIGN", (0, 0), (-1, -1), "TOP"),
                    ("TOPPADDING", (0, 0), (-1, -1), 2),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ]
            )
        )
        flow.append(pdf_table)
        hidden = len(table.rows) - len(shown)
        if hidden > 0:
            flow.append(_p(f"… and {hidden:,} more rows in {table.key}.csv.", styles["muted"]))
    if table.note:
        flow.append(_p(table.note, styles["muted"]))
    flow.append(Spacer(1, 6))
    return flow


class _NumberedCanvas(Canvas):  # type: ignore[misc]  # ReportLab has no type hints
    """Adds "Page X of Y" to every page once the total is known."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._pages: list[dict[str, Any]] = []

    def showPage(self) -> None:
        self._pages.append(dict(self.__dict__))
        self._startPage()

    def save(self) -> None:
        total = len(self._pages)
        for state in self._pages:
            self.__dict__.update(state)
            self.setFont(font_names()[0], 8)
            self.setFillColor(colors.HexColor("#5b6070"))
            self.drawRightString(A4[0] - MARGIN, 9 * mm, f"Page {self._pageNumber} of {total}")
            super().showPage()
        super().save()


def write_pdf(content: ReportContent, path: Path) -> int:
    """Write the report as an A4 PDF; returns the page count."""
    styles = _styles()
    meta = content.meta
    width = A4[0] - 2 * MARGIN
    flow: list[Any] = [
        _p(content.title, styles["title"]),
        _p(content.subtitle, styles["subtitle"]),
        _p(
            f"{meta.filter_text} · Generated {meta.local(meta.generated_at)} by tg_sales "
            f"{meta.app_version}",
            styles["muted"],
        ),
        Spacer(1, 6),
    ]
    for section in content.sections:
        if section.key in NEW_PAGE_SECTIONS:
            flow.append(PageBreak())
        flow.append(_p(section.title, styles["h2"]))
        flow.extend(_p(p, styles["body"]) for p in section.paragraphs)
        for bullet in section.bullets:
            flow.append(Paragraph("• " + escape(bullet), styles["body"]))
        for chart in section.charts:
            flow.append(KeepTogether([_p(chart.title, styles["h3"]), to_drawing(chart, width)]))
        for table in section.tables:
            flow.extend(_pdf_table(table, styles, width))
    document = SimpleDocTemplate(
        str(path),
        pagesize=A4,
        leftMargin=MARGIN,
        rightMargin=MARGIN,
        topMargin=MARGIN,
        bottomMargin=MARGIN + 4 * mm,
        title=f"{content.title} · {content.subtitle}",
        creator="tg_sales",
        author="tg_sales",
    )
    document.build(flow, canvasmaker=_NumberedCanvas)
    return pdf_page_count(path)


def pdf_page_count(path: Path) -> int:
    return len(PAGE_PATTERN.findall(path.read_bytes()))
