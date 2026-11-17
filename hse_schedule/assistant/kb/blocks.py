"""The unit both parsers emit and the chunker consumes."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Block:
    kind: str  # heading | clause | table | paragraph | faq
    text: str
    page: int | None = None
    number: str | None = None  # «1.», «2.3.», «2.3.4.» or None
    head: list[str] = field(default_factory=list)  # tables: header row
    rows: list[list[str]] = field(default_factory=list)  # tables: body rows


def table_text(head: list[str], rows: list[list[str]]) -> str:
    """«шапка: значение; шапка: значение» per row — the number stays next to its column name."""
    lines = []
    for row in rows:
        pairs = [f"{h}: {c}" for h, c in zip(head, row) if c]
        lines.append("; ".join(pairs))
    return "\n".join(lines)


def clean(text: str | None) -> str:
    return " ".join((text or "").split())
