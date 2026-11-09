# Copyright 2013-present Tatum Games, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy
# of the License at: https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.

"""Report charts without a GUI toolkit: one layout, two outputs.

:func:`layout` turns a :class:`Chart` into simple shapes (rectangles, lines,
circles and text) with a legend, integer axis ticks and thinned x-axis labels
that never overlap. :func:`to_svg` writes those shapes as SVG (HTML preview)
and :func:`to_drawing` as a ReportLab vector drawing (PDF), so charts stay
sharp at any zoom level and on high-DPI screens. Text widths come from the
same font metrics the PDF uses.
"""

from __future__ import annotations

import html
import itertools
import math
from dataclasses import dataclass

from reportlab.graphics.shapes import Circle, Drawing, Line, Rect, String
from reportlab.lib.colors import HexColor
from reportlab.pdfbase.pdfmetrics import stringWidth

from tg_sales.reports.content import Chart
from tg_sales.reports.fonts import font_names

# Brand palette (the same hues as the app's chart colors).
SERIES_COLORS = ("#a787bd", "#86c4c2", "#c7d47f", "#f6d271", "#d87b7a")
TEXT = "#1f2430"
MUTED = "#5b6070"
GRID = "#d9dbe2"
FONT_SIZE = 8.5
LINE_HEIGHT = FONT_SIZE * 1.6


@dataclass(frozen=True)
class Shape:
    kind: str  # rect | line | circle | text
    x: float
    y: float  # top-left origin, y grows downwards
    w: float = 0.0
    h: float = 0.0
    color: str = TEXT
    text: str = ""
    stroke: float = 1.0
    anchor: str = "start"  # text: start | middle | end


def nice_max(value: float) -> int:
    """A round axis maximum at or above ``value`` (at least 1)."""
    if value <= 1:
        return 1
    magnitude: float = 10.0 ** math.floor(math.log10(value))
    for step in (1, 2, 2.5, 5, 10):
        top = step * magnitude
        if top >= value:
            return max(1, math.ceil(top))
    return math.ceil(value)


def _ticks(top: int) -> list[int]:
    step = max(1, math.ceil(top / 5))
    return list(range(0, top + 1, step))


def text_width(value: str) -> float:
    return float(stringWidth(value, font_names()[0], FONT_SIZE))


def layout(chart: Chart, width: float = 520, height: float = 220) -> list[Shape]:
    shapes: list[Shape] = []
    names = list(chart.series)
    colors = {name: SERIES_COLORS[i % len(SERIES_COLORS)] for i, name in enumerate(names)}

    # Legend along the top, wrapping when needed.
    x, y = 4.0, 4.0
    for name in names:
        item = 12 + text_width(name) + 16
        if x + item > width - 4 and x > 4:
            x, y = 4.0, y + LINE_HEIGHT
        shapes.append(Shape("rect", x, y + 1, 8, 8, colors[name]))
        shapes.append(Shape("text", x + 12, y + FONT_SIZE, text=name))
        x += item
    top_margin = y + LINE_HEIGHT + 6

    values = [v for series in chart.series.values() for v in series]
    top = nice_max(max(values, default=0))
    ticks = _ticks(top)
    left = 8 + max(text_width(f"{t:,}") for t in ticks)
    bottom_margin = LINE_HEIGHT * 2
    px, py = left + 6, top_margin
    pw, ph = width - left - 12, height - top_margin - bottom_margin
    bottom = py + ph

    for tick in ticks:
        ty = bottom - ph * tick / top
        shapes.append(Shape("line", px, ty, pw, 0, GRID, stroke=0.6))
        shapes.append(
            Shape("text", px - 5, ty + FONT_SIZE / 3, text=f"{tick:,}", color=MUTED, anchor="end")
        )
    shapes.append(Shape("line", px, bottom, pw, 0, MUTED, stroke=0.9))

    count = len(chart.labels)
    if count == 0:
        shapes.append(
            Shape("text", px + pw / 2, py + ph / 2, text="No data", color=MUTED, anchor="middle")
        )
        return shapes
    slot = pw / count

    # X-axis labels, thinned so they never overlap.
    widest = max(text_width(label) for label in chart.labels) + 6
    every = max(1, math.ceil(widest / slot))
    last_right = -math.inf
    for index, label in enumerate(chart.labels):
        if index % every:
            continue
        cx = px + slot * (index + 0.5)
        label_width = text_width(label)
        tx = min(max(cx - label_width / 2, px), px + pw - label_width)
        if tx < last_right + 5:
            continue
        shapes.append(Shape("text", tx, bottom + LINE_HEIGHT, text=label, color=MUTED))
        last_right = tx + label_width

    if chart.kind == "line":
        for name in names:
            points = [
                (px + slot * (i + 0.5), bottom - ph * value / top)
                for i, value in enumerate(chart.series[name])
            ]
            for (x1, y1), (x2, y2) in itertools.pairwise(points):
                shapes.append(Shape("line", x1, y1, x2 - x1, y2 - y1, colors[name], stroke=1.8))
            shapes.extend(Shape("circle", cx, cy, 1.8, 0, colors[name]) for cx, cy in points)
    else:
        group = slot * 0.8
        bar = group / max(1, len(names))
        for i in range(count):
            gx = px + slot * i + (slot - group) / 2
            for j, name in enumerate(names):
                value = chart.series[name][i]
                bar_height = ph * value / top
                if bar_height > 0:
                    shapes.append(
                        Shape(
                            "rect",
                            gx + bar * j,
                            bottom - bar_height,
                            bar * 0.92,
                            bar_height,
                            colors[name],
                        )
                    )
    return shapes


def to_svg(chart: Chart, width: float = 520, height: float = 220) -> str:
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width:g} {height:g}" '
        f'width="{width:g}" height="{height:g}" role="img" '
        f'aria-label="{html.escape(chart.title, quote=True)}" '
        f'font-family="Helvetica, Arial, sans-serif" font-size="{FONT_SIZE}">',
        f'<rect x="0" y="0" width="{width:g}" height="{height:g}" fill="#ffffff"/>',
    ]
    for s in layout(chart, width, height):
        if s.kind == "rect":
            parts.append(
                f'<rect x="{s.x:.2f}" y="{s.y:.2f}" width="{s.w:.2f}" height="{s.h:.2f}" '
                f'fill="{s.color}"/>'
            )
        elif s.kind == "line":
            parts.append(
                f'<line x1="{s.x:.2f}" y1="{s.y:.2f}" x2="{s.x + s.w:.2f}" y2="{s.y + s.h:.2f}" '
                f'stroke="{s.color}" stroke-width="{s.stroke:g}"/>'
            )
        elif s.kind == "circle":
            parts.append(f'<circle cx="{s.x:.2f}" cy="{s.y:.2f}" r="{s.w:g}" fill="{s.color}"/>')
        else:
            parts.append(
                f'<text x="{s.x:.2f}" y="{s.y:.2f}" fill="{s.color}" text-anchor="{s.anchor}">'
                f"{html.escape(s.text)}</text>"
            )
    parts.append("</svg>")
    return "".join(parts)


def to_drawing(chart: Chart, width: float = 480, height: float = 210) -> Drawing:
    drawing = Drawing(width, height)
    for s in layout(chart, width, height):
        color = HexColor(s.color)
        if s.kind == "rect":
            drawing.add(Rect(s.x, height - s.y - s.h, s.w, s.h, fillColor=color, strokeColor=None))
        elif s.kind == "line":
            drawing.add(
                Line(
                    s.x,
                    height - s.y,
                    s.x + s.w,
                    height - s.y - s.h,
                    strokeColor=color,
                    strokeWidth=s.stroke,
                )
            )
        elif s.kind == "circle":
            drawing.add(Circle(s.x, height - s.y, s.w, fillColor=color, strokeColor=None))
        else:
            drawing.add(
                String(
                    s.x,
                    height - s.y,
                    s.text,
                    fontName=font_names()[0],
                    fontSize=FONT_SIZE,
                    fillColor=color,
                    textAnchor=s.anchor,
                )
            )
    return drawing
