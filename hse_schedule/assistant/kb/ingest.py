"""Load the manifest into the knowledge base: parse, cut, store — only what changed."""

from __future__ import annotations

import hashlib
import json
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from . import chunker
from .models import KbDocument
from .store import ChunkData, replace_chunks, upsert_document


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def parse_file(path: Path):
    if path.suffix.lower() == ".pdf":
        from .parse_pdf import parse
    elif path.suffix.lower() in (".html", ".htm"):
        from .parse_html import parse
    else:
        raise ValueError(f"{path.name}: неизвестный формат")
    return parse(path)


async def ingest_manifest(session: AsyncSession, manifest_path: str | Path, root: str | Path | None = None) -> list[dict]:
    """For each manifest entry: same sha256 → skip; otherwise upsert the document and replace its fragments."""
    manifest_path = Path(manifest_path)
    root = Path(root) if root else manifest_path.parent
    entries = json.loads(manifest_path.read_text(encoding="utf-8"))["documents"]
    report = []
    for entry in entries:
        path = root / entry["source_path"]
        if not path.is_file():
            raise FileNotFoundError(f"{entry['doc_id']}: нет файла {path}")
        digest = sha256_file(path)
        existing = await session.scalar(select(KbDocument).where(KbDocument.doc_id == entry["doc_id"]))
        if existing and existing.content_hash == digest and existing.status == entry["status"]:
            report.append({"doc_id": entry["doc_id"], "status": "unchanged", "chunks": None, "tables": None})
            continue
        chunks = chunker.chunk(parse_file(path), entry["title"])
        if not chunks:
            raise ValueError(f"{path.name}: после разбора не осталось ни одного фрагмента")
        document = await upsert_document(
            session, doc_id=entry["doc_id"], title=entry["title"], kind=entry["kind"], version=str(entry["version"]),
            status=entry["status"], priority=int(entry["priority"]), audience=entry["audience"],
            source_path=entry["source_path"], content_hash=digest,
            effective_from=date.fromisoformat(entry["effective_from"]) if entry.get("effective_from") else None)
        await replace_chunks(session, document, [
            ChunkData(text=c.text, section_path=c.section_path, kind=c.kind, tokens=c.tokens, content_hash=c.content_hash, page=c.page)
            for c in chunks])
        report.append({"doc_id": entry["doc_id"], "status": "indexed", "chunks": len(chunks),
                       "tables": sum(c.kind == "table" for c in chunks)})
    await session.commit()
    return report
