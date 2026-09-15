"""Portable embedded-font PDF from the same content tree as Markdown."""

from __future__ import annotations

import hashlib
import html
import io
from pathlib import Path
from typing import Any

import reportlab
from reportlab.graphics.shapes import Drawing, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (
    Flowable,
    LongTable,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    TableStyle,
)

from skills._shared.fit_weekly import report_view

FONT = (
    Path(__file__).resolve().parents[1]
    / "assets/report-fonts/TrainLabReportSans-Regular.ttf"
)
FONT_NAME = "TrainLabReportCJK"


def identity() -> str:
    h = hashlib.sha256(reportlab.Version.encode())
    for path in (
        FONT,
        Path(__file__),
        Path(__file__).with_name("report_view.py"),
        Path(__file__).with_name("report_markdown.py"),
    ):
        if path.is_symlink() or not path.is_file():
            raise ValueError("report_render_dependency_missing")
        h.update(path.name.encode())
        h.update(path.read_bytes())
    return h.hexdigest()


def render(view: dict[str, Any]) -> bytes:
    identity()
    if FONT_NAME not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(FONT_NAME, str(FONT)))
    body = ParagraphStyle(
        "Body",
        fontName=FONT_NAME,
        fontSize=9.5,
        leading=15,
        textColor=colors.HexColor("#243447"),
        wordWrap="CJK",
        spaceAfter=6,
        alignment=TA_LEFT,
        splitLongWords=True,
    )
    small = ParagraphStyle("Table", parent=body, fontSize=8.5, leading=13, spaceAfter=0)
    headings = {
        level: ParagraphStyle(
            f"Heading{level}",
            parent=body,
            fontSize=size,
            leading=size * 1.45,
            spaceBefore=12 if level > 1 else 0,
            spaceAfter=8,
            textColor=colors.HexColor("#183F50"),
            keepWithNext=True,
        )
        for level, size in ((1, 23), (2, 15), (3, 11), (4, 10))
    }

    def paragraph(value: str, style: ParagraphStyle = body) -> Paragraph:
        return Paragraph(html.escape(value, quote=False).replace("\n", "<br/>"), style)

    story: list[Flowable] = []
    width = A4[0] - 88
    for block in report_view.blocks(view):
        kind = block["kind"]
        if kind == "heading":
            story.append(paragraph(block["text"], headings[block["level"]]))
        elif kind == "paragraph":
            story.append(paragraph(block["text"]))
        elif kind == "table":
            rows = [
                [paragraph(v, small) for v in row]
                for row in [block["headers"], *block["rows"]]
            ]
            table = LongTable(
                rows,
                colWidths=[width / len(block["headers"])] * len(block["headers"]),
                repeatRows=1,
                splitByRow=1,
                splitInRow=1,
                hAlign="LEFT",
            )
            table.setStyle(
                TableStyle(
                    [
                        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#E4EFF0")),
                        (
                            "ROWBACKGROUNDS",
                            (0, 1),
                            (-1, -1),
                            [colors.white, colors.HexColor("#F5F8F9")],
                        ),
                        ("VALIGN", (0, 0), (-1, -1), "TOP"),
                        ("LEFTPADDING", (0, 0), (-1, -1), 7),
                        ("RIGHTPADDING", (0, 0), (-1, -1), 7),
                        ("TOPPADDING", (0, 0), (-1, -1), 6),
                        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
                        ("LINEBELOW", (0, 0), (-1, 0), 0.6, colors.HexColor("#83A8B0")),
                    ]
                )
            )
            story.extend([table, Spacer(1, 8)])
        elif kind == "chart":
            story.append(paragraph(block["title"], headings[3]))
            rows = block["rows"]
            # One small chart per bounded set of 8 sports; zero remains zero.
            for offset in range(0, len(rows), 8):
                chunk = rows[offset : offset + 8]
                drawing = Drawing(width, 34 * len(chunk) + 6)
                largest = max((r[1] for r in rows), default=0)
                for i, (name, value, status) in enumerate(chunk):
                    y = 34 * (len(chunk) - i - 1) + 12
                    drawing.add(
                        String(
                            0,
                            y + 12,
                            f"{name} / {value:g} 秒 / {status}",
                            fontName=FONT_NAME,
                            fontSize=9,
                        )
                    )
                    background = Rect(0, y - 3, width, 7)
                    background.fillColor = colors.HexColor("#EDF2F3")
                    background.strokeColor = None
                    drawing.add(background)
                    if largest > 0 and value > 0:
                        bar = Rect(0, y - 3, width * value / largest, 7)
                        bar.fillColor = colors.HexColor("#3C8088")
                        bar.strokeColor = None
                        drawing.add(bar)
                story.extend([drawing, Spacer(1, 8)])
    output = io.BytesIO()
    document = SimpleDocTemplate(
        output,
        pagesize=A4,
        rightMargin=44,
        leftMargin=44,
        topMargin=42,
        bottomMargin=42,
        title="TrainLab 每周运动报告",
        author="TrainLab",
        pageCompression=1,
        invariant=1,
    )

    def footer(canvas: Any, doc: Any) -> None:
        canvas.saveState()
        canvas.setFont(FONT_NAME, 8)
        canvas.setFillColor(colors.HexColor("#637984"))
        canvas.drawString(44, 23, "TrainLab / " + view["revision_id"])
        canvas.drawRightString(A4[0] - 44, 23, f"第 {doc.page} 页")
        canvas.restoreState()

    document.build(story, onFirstPage=footer, onLaterPages=footer)
    return output.getvalue()
