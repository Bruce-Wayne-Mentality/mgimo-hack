"""Storage helpers for the knowledge base: vectors as bytes, documents, fragments."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

import numpy as np
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from .models import KbChunk, KbDocument


def pack_vector(vector) -> bytes:
    return np.asarray(vector, dtype="<f4").tobytes()


def unpack_vector(data: bytes) -> np.ndarray:
    return np.frombuffer(data, dtype="<f4").astype(np.float32)


@dataclass
class ChunkData:
    text: str
    section_path: str
    kind: str
    tokens: int
    content_hash: str
    page: int | None = None


async def upsert_document(session: AsyncSession, *, doc_id: str, title: str, kind: str, version: str, status: str,
                          priority: int, audience: str, source_path: str, content_hash: str,
                          effective_from: date | None = None) -> KbDocument:
    document = await session.scalar(select(KbDocument).where(KbDocument.doc_id == doc_id))
    if document is None:
        document = KbDocument(doc_id=doc_id)
        session.add(document)
    document.title, document.kind, document.version, document.status = title, kind, version, status
    document.priority, document.audience, document.source_path = priority, audience, source_path
    document.content_hash, document.effective_from = content_hash, effective_from
    await session.flush()
    return document


async def replace_chunks(session: AsyncSession, document: KbDocument, chunks: list[ChunkData]) -> list[KbChunk]:
    """Swap all fragments of a document in the caller's transaction.

    A fragment whose text is unchanged keeps its vector, so re-indexing after an
    edit recomputes embeddings only for fragments that really changed.
    """
    old = (await session.scalars(select(KbChunk).where(KbChunk.document_id == document.id))).all()
    vectors = {c.content_hash: (c.embedding, c.embedding_model) for c in old if c.embedding is not None}
    await session.execute(delete(KbChunk).where(KbChunk.document_id == document.id))
    await session.flush()
    created = []
    for ord_, chunk in enumerate(chunks):
        embedding, model = vectors.get(chunk.content_hash, (None, None))
        row = KbChunk(document_id=document.id, ord=ord_, section_path=chunk.section_path[:300], page=chunk.page,
                      kind=chunk.kind, text=chunk.text, tokens=chunk.tokens, content_hash=chunk.content_hash,
                      embedding=embedding, embedding_model=model)
        session.add(row)
        created.append(row)
    await session.flush()
    return created


async def active_chunks(session: AsyncSession) -> list[KbChunk]:
    """Fragments of active documents only, with their document loaded."""
    rows = await session.scalars(
        select(KbChunk).join(KbDocument).where(KbDocument.status == "active")
        .options(selectinload(KbChunk.document)).order_by(KbDocument.doc_id, KbChunk.ord))
    return list(rows.all())
