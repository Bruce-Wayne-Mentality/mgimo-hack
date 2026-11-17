"""PDF regulations → blocks: headings, numbered clauses, tables, paragraphs.

Rules:
- text inside a table's box is taken from the table, not from the text lines;
- a table that continues on the next page with the same header is one block;
- lines repeated on most pages (running headers, «Страница N») are dropped;
- everything before the first numbered heading (the «УТВЕРЖДАЮ» block and the
  title) and everything from «Лист согласования» on is service text.

pdfplumber is imported inside the function: it is an optional dependency
(pip install -e .[kb]) needed only to build the base, not to run the app.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path

from .blocks import Block, clean, table_text

HEADING = re.compile(r"^(\d{1,2})\.\s+([А-ЯЁA-Z].{0,90})$")
CLAUSE = re.compile(r"^(\d{1,2}(?:\.\d{1,2})+\.)\s+(.+)$")
CAPTION = re.compile(r"^Таблица\s+\d+\.")
SERVICE = re.compile(r"^Лист согласования", re.IGNORECASE)


def _noise(pages_lines: list[list[str]]) -> set[str]:
    """Lines (digits normalised) present on most pages: running headers and footers."""
    if len(pages_lines) < 2:
        return set()
    counts = Counter()
    for lines in pages_lines:
        counts.update({re.sub(r"\d+", "#", line) for line in lines})
    threshold = max(2, math.ceil(len(pages_lines) * 0.6))
    return {line for line, count in counts.items() if count >= threshold}


def parse(path: str | Path) -> list[Block]:
    import pdfplumber

    items: list[tuple[int, float, object]] = []  # (page, top, line text | table)
    pages_lines: list[list[str]] = []
    with pdfplumber.open(str(path)) as pdf:
        for number, page in enumerate(pdf.pages, start=1):
            tables = page.find_tables()
            boxes = [t.bbox for t in tables]
            lines = []
            for line in page.extract_text_lines():
                inside = any(line["top"] >= b[1] - 1 and line["bottom"] <= b[3] + 1 for b in boxes)
                if not inside and clean(line["text"]):
                    lines.append(clean(line["text"]))
                    items.append((number, line["top"], clean(line["text"])))
            pages_lines.append(lines)
            for t in tables:
                rows = [[clean(cell) for cell in row] for row in t.extract()]
                if rows:
                    items.append((number, t.bbox[1], rows))
    noise = _noise(pages_lines)
    items.sort(key=lambda item: (item[0], item[1]))

    blocks: list[Block] = []
    started = False
    for page, _top, item in items:
        if isinstance(item, list):
            if not started:
                continue
            head, rows = item[0], item[1:]
            previous = blocks[-1] if blocks else None
            if previous and previous.kind == "table" and previous.head == head and previous.page is not None and previous.page < page:
                previous.rows.extend(rows)  # the same table continued on the next page
                previous.text = table_text(previous.head, previous.rows)
            else:
                blocks.append(Block("table", table_text(head, rows), page=page, head=head, rows=rows))
            continue
        line = item
        if re.sub(r"\d+", "#", line) in noise:
            continue
        if SERVICE.match(line):
            break
        heading, clause = HEADING.match(line), CLAUSE.match(line)
        if heading and not clause and not line.endswith((",", ";")):
            started = True
            blocks.append(Block("heading", line, page=page, number=f"{heading.group(1)}."))
        elif not started:
            continue
        elif clause:
            blocks.append(Block("clause", line, page=page, number=clause.group(1)))
        elif CAPTION.match(line):
            blocks.append(Block("paragraph", line, page=page))
        elif blocks and blocks[-1].kind in ("clause", "paragraph") and not CAPTION.match(blocks[-1].text):
            blocks[-1].text = f"{blocks[-1].text} {line}"  # a wrapped line of the same clause
        else:
            blocks.append(Block("paragraph", line, page=page))
    if not any(b.text for b in blocks):
        raise ValueError(f"{Path(path).name}: в PDF нет текстового слоя (скан?) — разобрать нельзя")
    return blocks
