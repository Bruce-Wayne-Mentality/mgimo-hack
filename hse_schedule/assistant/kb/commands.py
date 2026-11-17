"""CLI commands of the knowledge base: kb-build, kb-embed, kb-stats.

kb-embed computes a vector once per fragment and again only when the text or
the model changed; every batch is committed, so a network break does not lose
what was already computed.
"""

from __future__ import annotations

import asyncio
from collections import Counter
from pathlib import Path

from sqlalchemy import func, or_, select

from ...db import Database
from .ingest import ingest_manifest
from .models import KbChunk, KbDocument, KbGap
from .store import pack_vector

PAUSE = 0.5  # seconds between batches: one shared stream on a Freemium key


async def build(database: Database, manifest: Path) -> list[dict]:
    async with database.session() as db:
        report = await ingest_manifest(db, manifest)
    return report


async def embed(database: Database, giga, *, force: bool = False, limit: int | None = None,
                batch_size: int = 16, pause: float = PAUSE) -> dict:
    """Fill missing vectors (or all of them with force). Returns counts; raises GigaChatUnavailable."""
    model = giga.embed_model
    async with database.session() as db:
        query = select(KbChunk.id, KbChunk.text).join(KbDocument).where(KbDocument.status == "active").order_by(KbChunk.id)
        if not force:
            query = query.where(or_(KbChunk.embedding.is_(None), KbChunk.embedding_model != model))
        rows = (await db.execute(query)).all()
    if limit is not None:
        rows = rows[:limit]
    done = 0
    for offset in range(0, len(rows), batch_size):
        batch = rows[offset:offset + batch_size]
        vectors = await giga.embed([text for _, text in batch], model=model)
        async with database.session() as db:
            for (chunk_id, _), vector in zip(batch, vectors):
                chunk = await db.get(KbChunk, chunk_id)
                chunk.embedding, chunk.embedding_model = pack_vector(vector), model
            await db.commit()  # each batch is saved on its own
        done += len(batch)
        if offset + batch_size < len(rows) and pause:
            await asyncio.sleep(pause)
    return {"embedded": done, "model": model}


async def stats(database: Database) -> dict:
    async with database.session() as db:
        documents = Counter(dict((await db.execute(select(KbDocument.status, func.count()).group_by(KbDocument.status))).all()))
        chunks = await db.scalar(select(func.count()).select_from(KbChunk)) or 0
        embedded = await db.scalar(select(func.count()).select_from(KbChunk).where(KbChunk.embedding.is_not(None))) or 0
        models = dict((await db.execute(select(KbChunk.embedding_model, func.count()).where(KbChunk.embedding.is_not(None))
                                        .group_by(KbChunk.embedding_model))).all())
        gaps = await db.scalar(select(func.count()).select_from(KbGap).where(KbGap.status == "open")) or 0
    return {"documents": dict(documents), "chunks": chunks, "embedded": embedded, "models": models, "open_gaps": gaps}
