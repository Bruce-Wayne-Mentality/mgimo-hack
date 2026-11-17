"""Server-side PDF of an issued document (K2) with a verification QR code.

Onest (SIL OFL 1.1, bundled in assets/fonts) renders Cyrillic. Every page
carries the «concept, no legal force» mark required by section 5.
"""

from __future__ import annotations

import io
from dataclasses import dataclass, field
from pathlib import Path

import segno
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Flowable, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FONTS = Path(__file__).resolve().parents[1] / "assets" / "fonts"
PRIMARY = colors.HexColor("#2F6AE6")
TEXT = colors.HexColor("#121826")
MUTED = colors.HexColor("#8A93A8")
TILE = colors.HexColor("#EEF2FB")
LINE = colors.HexColor("#DCE3F2")

_registered = False


def _fonts() -> None:
    global _registered
    if _registered:
        return
    pdfmetrics.registerFont(TTFont("Onest", str(FONTS / "Onest_400Regular.ttf")))
    pdfmetrics.registerFont(TTFont("Onest-Medium", str(FONTS / "Onest_500Medium.ttf")))
    pdfmetrics.registerFont(TTFont("Onest-Bold", str(FONTS / "Onest_700Bold.ttf")))
    pdfmetrics.registerFontFamily("Onest", normal="Onest", bold="Onest-Medium", italic="Onest", boldItalic="Onest-Medium")
    _registered = True


@dataclass
class DocumentContent:
    title: str
    number: str
    issued_on: str
    paragraphs: list[str]
    facts: list[tuple[str, str]]
    verify_url: str
    signature: str
    table: list[list[str]] | None = None
    table_title: str | None = None
    signer: str = "Специалист деканата (демо)"
    notes: list[str] = field(default_factory=list)


class QRCode(Flowable):
    def __init__(self, data: str, size: float) -> None:
        super().__init__()
        self.qr = segno.make(data, error="m")
        self.size = size
        self.width = self.height = size

    def draw(self) -> None:
        matrix = list(self.qr.matrix)
        count = len(matrix)
        quiet = 2
        cell = self.size / (count + 2 * quiet)
        canvas = self.canv
        canvas.setFillColor(colors.white)
        canvas.rect(0, 0, self.size, self.size, stroke=0, fill=1)
        canvas.setFillColor(colors.black)
        for row_index, row in enumerate(matrix):
            for col_index, value in enumerate(row):
                if value:
                    x = (col_index + quiet) * cell
                    y = self.size - (row_index + quiet + 1) * cell
                    canvas.rect(x, y, cell + 0.05, cell + 0.05, stroke=0, fill=1)


def _styles() -> dict[str, ParagraphStyle]:
    return {
        "title": ParagraphStyle("title", fontName="Onest-Medium", fontSize=22, leading=27, textColor=TEXT, spaceAfter=4),
        "meta": ParagraphStyle("meta", fontName="Onest", fontSize=9.5, leading=13, textColor=MUTED),
        "body": ParagraphStyle("body", fontName="Onest", fontSize=11.5, leading=17, textColor=TEXT, alignment=TA_LEFT, spaceAfter=7),
        "label": ParagraphStyle("label", fontName="Onest", fontSize=8.5, leading=11, textColor=MUTED),
        "value": ParagraphStyle("value", fontName="Onest-Medium", fontSize=10.5, leading=13.5, textColor=TEXT),
        "cell": ParagraphStyle("cell", fontName="Onest", fontSize=9.5, leading=12, textColor=TEXT),
        "head": ParagraphStyle("head", fontName="Onest-Medium", fontSize=9, leading=12, textColor=MUTED),
        "small": ParagraphStyle("small", fontName="Onest", fontSize=8.5, leading=11.5, textColor=MUTED),
        "section": ParagraphStyle("section", fontName="Onest-Medium", fontSize=12, leading=16, textColor=TEXT, spaceBefore=6, spaceAfter=6),
    }


def _decorate(canvas, doc) -> None:
    width, height = A4
    canvas.saveState()
    # Brand mark: our own sign, not a university logo.
    canvas.setFillColor(PRIMARY)
    canvas.roundRect(20 * mm, height - 25 * mm, 9 * mm, 9 * mm, 2.4 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Onest-Bold", 12)
    canvas.drawCentredString(24.5 * mm, height - 22.1 * mm, "Д")
    canvas.setFillColor(TEXT)
    canvas.setFont("Onest-Medium", 11)
    canvas.drawString(32 * mm, height - 19.6 * mm, "Цифровой деканат")
    canvas.setFillColor(MUTED)
    canvas.setFont("Onest", 8.5)
    canvas.drawString(32 * mm, height - 23.6 * mm, "Концепт для конкурса · вымышленный вуз")
    canvas.setStrokeColor(LINE)
    canvas.setLineWidth(0.6)
    canvas.line(20 * mm, height - 29 * mm, width - 20 * mm, height - 29 * mm)
    # Mandatory mark on every page.
    canvas.setFillColor(TILE)
    canvas.roundRect(20 * mm, 10 * mm, width - 40 * mm, 9 * mm, 2 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.HexColor("#5A6478"))
    canvas.setFont("Onest-Medium", 8.5)
    canvas.drawString(24 * mm, 13.4 * mm, "Концепт конкурса, не имеет юридической силы. Демо-подпись — не УКЭП.")
    canvas.setFont("Onest", 8.5)
    canvas.drawRightString(width - 24 * mm, 13.4 * mm, f"стр. {doc.page}")
    canvas.restoreState()


def render(content: DocumentContent) -> bytes:
    _fonts()
    styles = _styles()
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4, leftMargin=20 * mm, rightMargin=20 * mm, topMargin=36 * mm, bottomMargin=26 * mm,
        title=f"{content.title} {content.number}", author="Цифровой деканат (концепт)",
        subject="Демонстрационный документ, не имеет юридической силы", creator="Цифровой деканат",
    )
    story: list = [
        Paragraph(f"№ {content.number} · от {content.issued_on}", styles["meta"]),
        Spacer(1, 3 * mm),
        Paragraph(content.title, styles["title"]),
        Spacer(1, 4 * mm),
    ]
    for text in content.paragraphs:
        story.append(Paragraph(text, styles["body"]))
    if content.facts:
        rows = []
        pairs = list(content.facts)
        for index in range(0, len(pairs), 2):
            row = []
            for label, value in pairs[index:index + 2]:
                row.append([Paragraph(label, styles["label"]), Paragraph(value, styles["value"])])
            if len(row) == 1:
                row.append("")
            rows.append(row)
        table = Table(rows, colWidths=[85 * mm, 85 * mm])
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), TILE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 4 * mm),
            ("TOPPADDING", (0, 0), (-1, -1), 2.6 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6 * mm),
            ("LINEBELOW", (0, 0), (-1, -2), 0.6, colors.white),
            ("LINEAFTER", (0, 0), (0, -1), 0.6, colors.white),
        ]))
        story += [Spacer(1, 3 * mm), table, Spacer(1, 5 * mm)]
    if content.table:
        if content.table_title:
            story.append(Paragraph(content.table_title, styles["section"]))
        head, *body = content.table
        data = [[Paragraph(cell, styles["head"]) for cell in head]] + [[Paragraph(cell, styles["cell"]) for cell in row] for row in body]
        widths = [100 * mm] + [70 * mm / (len(head) - 1)] * (len(head) - 1)
        table = Table(data, colWidths=widths, repeatRows=1)
        table.setStyle(TableStyle([
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, LINE),
            ("LINEBELOW", (0, 1), (-1, -1), 0.4, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 1.8 * mm),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 1.8 * mm),
            ("LEFTPADDING", (0, 0), (-1, -1), 1.5 * mm),
        ]))
        story += [table, Spacer(1, 5 * mm)]
    for note in content.notes:
        story.append(Paragraph(note, styles["small"]))
    if content.notes:
        story.append(Spacer(1, 4 * mm))

    signature_block = Table(
        [[
            QRCode(content.verify_url, 34 * mm),
            [
                Paragraph("Проверка подлинности", styles["value"]),
                Spacer(1, 1.5 * mm),
                Paragraph("Наведите камеру на QR-код или откройте ссылку — откроется публичная страница проверки.", styles["small"]),
                Spacer(1, 1.5 * mm),
                Paragraph(content.verify_url, styles["small"]),
                Spacer(1, 3 * mm),
                Paragraph(f"{content.signer}", styles["value"]),
                Paragraph(f"Демо-подпись (не УКЭП): HMAC-SHA256 {content.signature[:16]}…", styles["small"]),
            ],
        ]],
        colWidths=[40 * mm, 130 * mm],
    )
    signature_block.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOX", (0, 0), (-1, -1), 0.6, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 3 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 3 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3 * mm),
    ]))
    story.append(KeepTogether([Spacer(1, 2 * mm), signature_block]))
    doc.build(story, onFirstPage=_decorate, onLaterPages=_decorate)
    return buffer.getvalue()
