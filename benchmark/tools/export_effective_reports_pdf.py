#!/usr/bin/env python3
"""Export the timestamped effective-result Markdown reports as landscape PDFs."""

from __future__ import annotations

import re
from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.platypus import Image, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle


ROOT = Path(__file__).resolve().parents[2]
REPORTS = [
    ROOT / "docs/all_core_results/forecasting_transpose_20261023_1158/effective_by_type_bars_20261023_125229/effective_by_type_bars_20261023_125229.md",
    ROOT / "docs/all_core_results/forecasting_transpose_20261023_1158/effective_by_type_20261023_124601/effective_by_type_20261023_124601.md",
]
OUTPUT = ROOT / "output/pdf"
PAGE = landscape(A4)


def clean_markup(value: str) -> str:
    value = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", value)
    value = value.replace("**", "").replace("`", "")
    value = value.replace("·", " / ")
    value = value.replace("<", "&lt;").replace(">", "&gt;").replace("&lt;", "&lt;")
    return value


def on_page(canvas, doc) -> None:
    canvas.saveState()
    canvas.setFont("STSong-Light", 7)
    canvas.setFillColor(colors.HexColor("#71808e"))
    canvas.drawRightString(PAGE[0] - 14 * mm, 7 * mm, str(doc.page))
    canvas.restoreState()


def convert(report: Path, destination: Path) -> None:
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdfmetrics.registerFontFamily("STSong-Light", normal="STSong-Light", bold="STSong-Light",
                                  italic="STSong-Light", boldItalic="STSong-Light")
    base = getSampleStyleSheet()
    styles = {
        "title": ParagraphStyle("ReportTitle", parent=base["Title"], fontName="STSong-Light", fontSize=19,
                                 leading=25, textColor=colors.HexColor("#263442"), alignment=TA_LEFT, spaceAfter=10),
        "h2": ParagraphStyle("ReportH2", parent=base["Heading2"], fontName="STSong-Light", fontSize=13,
                              leading=18, textColor=colors.HexColor("#263442"), spaceBefore=7, spaceAfter=7),
        "body": ParagraphStyle("ReportBody", parent=base["BodyText"], fontName="STSong-Light", fontSize=8.5,
                                leading=12, textColor=colors.HexColor("#354252"), spaceAfter=6),
        "table": ParagraphStyle("ReportTable", parent=base["BodyText"], fontName="STSong-Light", fontSize=7.2,
                                 leading=9, textColor=colors.HexColor("#263442")),
        "table_header": ParagraphStyle("ReportTableHeader", parent=base["BodyText"], fontName="STSong-Light",
                                        fontSize=7.1, leading=9, textColor=colors.HexColor("#263442")),
    }
    page_width, page_height = PAGE
    doc = SimpleDocTemplate(str(destination), pagesize=PAGE, rightMargin=13 * mm, leftMargin=13 * mm,
                            topMargin=12 * mm, bottomMargin=13 * mm, title=report.stem)
    max_width = page_width - 26 * mm
    max_height = page_height - 49 * mm
    story = []
    lines = report.read_text(encoding="utf-8").splitlines()
    table_lines = []
    section_started = False

    def flush_table() -> None:
        nonlocal table_lines
        if not table_lines:
            return
        rows = []
        for line in table_lines:
            cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
            if cells and all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
                continue
            rows.append([Paragraph(clean_markup(cell), styles["table_header"] if not rows else styles["table"])
                         for cell in cells])
        if rows:
            first_width = 115
            col_widths = [first_width, 59] + [(max_width - first_width - 59) / 6] * 6
            table = Table(rows, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
            table.setStyle(TableStyle([
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#eaf0f4")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#263442")),
                ("FONTNAME", (0, 0), (-1, -1), "STSong-Light"),
                ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                ("ALIGN", (1, 0), (-1, -1), "RIGHT"),
                ("LEFTPADDING", (0, 0), (-1, -1), 4),
                ("RIGHTPADDING", (0, 0), (-1, -1), 4),
                ("TOPPADDING", (0, 0), (-1, -1), 3),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
                ("LINEBELOW", (0, 0), (-1, 0), 0.7, colors.HexColor("#aebbc5")),
                ("LINEBELOW", (0, 1), (-1, -1), 0.35, colors.HexColor("#d6dfe5")),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#f7f9fa")]),
            ]))
            story.append(table)
            story.append(Spacer(1, 8))
        table_lines = []

    for line in lines:
        stripped = line.strip()
        if stripped.startswith("|"):
            table_lines.append(stripped)
            continue
        flush_table()
        if not stripped:
            continue
        if stripped.startswith("## "):
            if section_started:
                story.append(PageBreak())
            section_started = True
            heading = Paragraph(clean_markup(stripped[3:]), styles["h2"])
            story.append(heading)
        elif stripped.startswith("# "):
            story.append(Paragraph(clean_markup(stripped[2:]), styles["title"]))
        elif stripped.startswith("!["):
            match = re.match(r"!\[([^\]]*)\]\(([^)]+)\)", stripped)
            if match:
                image_path = (report.parent / match.group(2)).resolve()
                image = Image(str(image_path))
                ratio = min(max_width / image.imageWidth, max_height / image.imageHeight, 1)
                image.drawWidth *= ratio
                image.drawHeight *= ratio
                story.append(KeepTogether([image, Spacer(1, 5)]))
        elif stripped.startswith("["):
            continue
        else:
            story.append(Paragraph(clean_markup(stripped), styles["body"]))

    flush_table()
    doc.build(story, onFirstPage=on_page, onLaterPages=on_page)


def main() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    for report in REPORTS:
        pdf_path = OUTPUT / f"{report.stem}.pdf"
        convert(report, pdf_path)
        print(f"{pdf_path} ({pdf_path.stat().st_size} bytes)")


if __name__ == "__main__":
    main()
