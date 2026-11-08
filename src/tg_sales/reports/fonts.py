"""Fonts for PDF reports.

ReportLab's built-in Helvetica only covers Western European text, so a
TrueType font with wider coverage is registered when one is available: the
``TG_SALES_PDF_FONT`` file, Windows' Segoe UI or Arial, or DejaVu Sans (Linux
and Docker images). Without one, Helvetica is used.
"""

from __future__ import annotations

import os
from functools import cache
from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFError, TTFont

FONT_ENV_VAR = "TG_SALES_PDF_FONT"
_CANDIDATES = (
    ("C:/Windows/Fonts/segoeui.ttf", "C:/Windows/Fonts/segoeuib.ttf"),
    ("C:/Windows/Fonts/arial.ttf", "C:/Windows/Fonts/arialbd.ttf"),
    (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ),
)


@cache
def font_names() -> tuple[str, str]:
    """(regular, bold) font names registered with ReportLab."""
    explicit = os.environ.get(FONT_ENV_VAR, "").strip()
    candidates = ((explicit, explicit),) if explicit else ()
    for regular, bold in (*candidates, *_CANDIDATES):
        if not Path(regular).is_file():
            continue
        try:
            pdfmetrics.registerFont(TTFont("TGSans", regular))
            bold_path = bold if Path(bold).is_file() else regular
            pdfmetrics.registerFont(TTFont("TGSans-Bold", bold_path))
        except TTFError:
            continue
        return "TGSans", "TGSans-Bold"
    return "Helvetica", "Helvetica-Bold"
