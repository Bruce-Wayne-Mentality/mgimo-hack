"""Blocks → fragments for search.

Rules (quality depends on them more than on anything else):
- one numbered clause = one fragment; sub-clauses (4.2.1 under 4.2) join their
  parent while the limit allows;
- a long clause is cut by sentences with a one-sentence overlap, every piece
  keeps the same section_path;
- a table is its own fragment with its caption and section title in front; it
  is not cut unless it exceeds twice the limit, then it is cut by rows with
  the header repeated;
- every fragment starts with «[Document title › section_path]» — a context
  prefix that helps both BM25 and vectors find the right document.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from .blocks import Block, table_text

LIMIT = 400  # approximate tokens per fragment
VERSION = "3"  # bump on any change of parsing or cutting rules: kb-build then re-cuts every document
SENTENCE = re.compile(r"(?<=[.!?…»])\s+(?=[А-ЯЁA-Z«(0-9])")


@dataclass
class Chunk:
    text: str  # with the context prefix
    body: str  # without it — what the student sees as the quote
    section_path: str
    page: int | None
    kind: str  # clause | table | faq | paragraph
    tokens: int

    @property
    def content_hash(self) -> str:
        return hashlib.sha256(self.text.encode("utf-8")).hexdigest()


def count_tokens(text: str) -> int:
    return round(len(text.split()) * 1.5)


def _section(block: Block) -> str:
    if block.number:
        return f"Раздел {block.number.rstrip('.')}"
    return block.text[:80]


def _sentences(text: str) -> list[str]:
    return [s for s in SENTENCE.split(text) if s.strip()]


def _split_long(body: str) -> list[str]:
    if count_tokens(body) <= LIMIT:
        return [body]
    sentences = _sentences(body)
    pieces, current = [], []
    for sentence in sentences:
        if current and count_tokens(" ".join(current + [sentence])) > LIMIT:
            pieces.append(" ".join(current))
            current = [current[-1]]  # one-sentence overlap
        current.append(sentence)
    if current:
        pieces.append(" ".join(current))
    return pieces


def chunk(blocks: list[Block], doc_title: str) -> list[Chunk]:
    chunks: list[Chunk] = []
    section = ""
    caption: str | None = None
    tables = faqs = 0
    parent: str | None = None  # number of the clause the last fragment holds

    def add(body: str, path: str, page: int | None, kind: str) -> None:
        # Tried in kb-eval: putting the section title into the prefix lowered hit@1 from 0.58 to 0.50
        # (docs/rag/EVAL.md), so the prefix names the section by number only.
        text = f"[{doc_title} › {path}]\n{body}" if path else f"[{doc_title}]\n{body}"
        chunks.append(Chunk(text=text, body=body, section_path=path, page=page, kind=kind, tokens=count_tokens(text)))

    for block in blocks:
        if block.kind == "heading":
            section, caption, parent = _section(block), None, None
            continue
        if block.kind == "paragraph" and block.text.startswith("Таблица"):
            caption = block.text
            continue
        if block.kind == "clause":
            number = block.number.rstrip(".")
            path = f"{section} › п. {number}" if section else f"п. {number}"
            last = chunks[-1] if chunks else None
            if (last and parent and last.kind == "clause" and number.startswith(parent + ".")
                    and count_tokens(last.body + " " + block.text) <= LIMIT):
                body = f"{last.body}\n{block.text}"
                chunks.pop()
                add(body, last.section_path, last.page, "clause")  # sub-clause joins its parent
                continue
            for piece in _split_long(block.text):
                add(piece, path, block.page, "clause")
            parent = number
            continue
        if block.kind == "table":
            tables += 1
            label = caption or f"Таблица {tables}"
            number = re.match(r"(Таблица\s+\d+)", label)
            name = number.group(1) if number else f"Таблица {tables}"
            if not number and section:
                label = f"Таблица {tables}: {section}"
            path = f"{section} › {name}" if section and number else label
            head_line = " | ".join(block.head)
            body = f"{label}\n{head_line}\n{block.text}"
            if count_tokens(body) <= 2 * LIMIT:
                add(body, path, block.page, "table")
            else:
                rows, part = [], 1
                for row in block.rows:
                    candidate = f"{label} (часть {part})\n{head_line}\n{table_text(block.head, rows + [row])}"
                    if rows and count_tokens(candidate) > LIMIT:
                        add(f"{label} (часть {part})\n{head_line}\n{table_text(block.head, rows)}", path, block.page, "table")
                        rows, part = [], part + 1
                    rows.append(row)
                if rows:
                    add(f"{label} (часть {part})\n{head_line}\n{table_text(block.head, rows)}", path, block.page, "table")
            caption, parent = None, None
            continue
        if block.kind == "faq":
            faqs += 1
            add(block.text, f"Частые вопросы › {faqs}. {block.number or ''}".strip(), block.page, "faq")
            parent = None
            continue
        # plain paragraph: merge with the previous paragraph of the same section while it fits
        last = chunks[-1] if chunks else None
        path = section or "Текст"
        if last and last.kind == "paragraph" and last.section_path == path and count_tokens(last.body + " " + block.text) <= LIMIT:
            body = f"{last.body}\n{block.text}"
            chunks.pop()
            add(body, path, last.page, "paragraph")
        else:
            for piece in _split_long(block.text):
                add(piece, path, block.page, "paragraph")
        parent = None
    return chunks


def matches_section(section_path: str, gold: str) -> bool:
    """Gold sections from questions.json: «4.2», «table-1», «faq-1»."""
    if gold.startswith("table-"):
        return re.search(rf"Таблица {gold.split('-')[1]}\b", section_path) is not None
    if gold.startswith("faq-"):
        return f"Частые вопросы › {gold.split('-')[1]}." in section_path
    return re.search(rf"п\. {re.escape(gold)}(?![\d.])", section_path) is not None
