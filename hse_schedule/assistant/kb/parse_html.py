"""Portal pages → blocks.

nav, header, footer, script and style are cut; blocks with class «important»
get the prefix «Важно: »; each <details> is one FAQ block (question from
<summary> plus the answer); tables are serialised like in PDF.
beautifulsoup4 is imported inside the function (optional dependency).
"""

from __future__ import annotations

from pathlib import Path

from .blocks import Block, clean, table_text


def parse(path: str | Path) -> list[Block]:
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(Path(path).read_text(encoding="utf-8"), "html.parser")
    for tag in soup(["nav", "header", "footer", "script", "style", "noscript"]):
        tag.decompose()
    root = soup.find("main") or soup.body or soup
    blocks: list[Block] = []
    for element in root.find_all(["h1", "h2", "h3", "p", "div", "table", "details"], recursive=True):
        if element.find_parent(["details", "table"]):
            continue  # handled together with its container
        classes = element.get("class") or []
        if element.name in ("h1", "h2", "h3"):
            blocks.append(Block("heading", clean(element.get_text(" "))))
        elif element.name == "div" and "important" in classes:
            blocks.append(Block("paragraph", "Важно: " + clean(element.get_text(" "))))
        elif element.name == "p":
            text = clean(element.get_text(" "))
            if text:
                blocks.append(Block("paragraph", text))
        elif element.name == "table":
            head = [clean(th.get_text(" ")) for th in element.select("thead th")] or \
                   [clean(c.get_text(" ")) for c in element.find("tr").find_all(["th", "td"])]
            body = element.select("tbody tr") or element.find_all("tr")[1:]
            rows = [[clean(td.get_text(" ")) for td in tr.find_all(["td", "th"])] for tr in body]
            blocks.append(Block("table", table_text(head, rows), head=head, rows=rows))
        elif element.name == "details":
            summary = element.find("summary")
            question = clean(summary.get_text(" ")) if summary else ""
            if summary:
                summary.extract()
            answer = clean(element.get_text(" "))
            blocks.append(Block("faq", f"{question} {answer}".strip(), number=question))
    if not any(b.text for b in blocks):
        raise ValueError(f"{Path(path).name}: на странице нет текста")
    return blocks
