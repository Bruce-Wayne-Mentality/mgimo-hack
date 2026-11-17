"""Staff side of the knowledge base: the queue of questions without an answer.

A refusal is not a dead end: the masked question lands here, a deanery
employee answers it, and with «publish» the answer becomes a new fragment of
the service document «faq-staff» — the same question is then answered without
the deanery. Rights come from accounts/policy.py only.
"""

from __future__ import annotations

import hashlib
import uuid

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from sqlalchemy import select

from ...accounts.policy import can_manage_kb
from ...accounts.router import ApiError
from ...accounts.service import CurrentSession
from ...db import utcnow
from ...ratelimit import RateLimiter
from . import STAFF_DOC
from .answerer import mask_question
from .chunker import count_tokens
from .models import KbChunk, KbDocument, KbGap
from .store import ChunkData, pack_vector, replace_chunks, upsert_document

STAFF_TITLE = "Ответы деканата на вопросы студентов"


class AnswerBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer_text: StrictStr = Field(min_length=3, max_length=2000)
    publish: StrictBool = False


def _gap_payload(gap: KbGap, nearest: KbChunk | None) -> dict:
    return {
        "id": str(gap.id), "question": gap.question_masked, "status": gap.status, "top_score": round(gap.top_score, 2),
        "nearest": {"title": nearest.document.title, "section_path": nearest.section_path} if nearest else None,
        "answer_text": gap.answer_text, "answered_by": gap.answered_by,
        "created_at": gap.created_at.isoformat(), "answered_at": gap.answered_at.isoformat() if gap.answered_at else None,
    }


async def publish_answer(db, question: str, answer: str) -> KbChunk:
    """Append one fragment to the staff FAQ document; earlier fragments keep their vectors."""
    document = await db.scalar(select(KbDocument).where(KbDocument.doc_id == STAFF_DOC))
    if document is None:
        document = await upsert_document(db, doc_id=STAFF_DOC, title=STAFF_TITLE, kind="regulation", version="1",
                                         status="active", priority=9, audience="all", source_path="staff",
                                         content_hash="staff")
    existing = (await db.scalars(select(KbChunk).where(KbChunk.document_id == document.id).order_by(KbChunk.ord))).all()
    keep = [ChunkData(text=c.text, section_path=c.section_path, kind=c.kind, tokens=c.tokens,
                      content_hash=c.content_hash, page=c.page) for c in existing]
    path = f"Ответ деканата № {len(existing) + 1}"
    body = f"Вопрос: {question}\nОтвет: {answer}"
    text = f"[{STAFF_TITLE} › {path}]\n{body}"


    keep.append(ChunkData(text=text, section_path=path, kind="faq", tokens=count_tokens(text),
                          content_hash=hashlib.sha256(text.encode("utf-8")).hexdigest()))
    rows = await replace_chunks(db, document, keep)
    return rows[-1]


def register_kb_routes(app: FastAPI, database) -> None:
    require_session = app.state.require_session
    limit = RateLimiter(limit=60, window=60)

    def staff(current: CurrentSession) -> None:
        if not can_manage_kb(current.user):
            raise ApiError(403, "forbidden", "Очередь базы знаний доступна сотрудникам деканата.")

    async def gap_or_404(db, gap_id: uuid.UUID) -> KbGap:
        gap = await db.get(KbGap, gap_id)
        if gap is None:
            raise ApiError(404, "not_found", "Вопрос не найден.")
        return gap

    @app.get("/api/staff/kb/gaps", tags=["knowledge base"])
    async def gaps(request: Request, status: str = "open", current: CurrentSession = Depends(require_session)) -> dict:
        staff(current)
        limit.check(request, "kb-gaps", str(current.user.id))
        if status not in ("open", "answered", "rejected", "all"):
            raise ApiError(422, "bad_status", "Неизвестный статус.")
        async with database.session() as db:
            query = select(KbGap).order_by(KbGap.created_at.desc()).limit(200)
            if status != "all":
                query = query.where(KbGap.status == status)
            rows = (await db.scalars(query)).all()
            items = []
            for gap in rows:
                nearest = None
                if gap.top_chunk_id:
                    nearest = await db.scalar(select(KbChunk).where(KbChunk.id == gap.top_chunk_id))
                    if nearest is not None:
                        await db.refresh(nearest, ["document"])
                items.append(_gap_payload(gap, nearest))
            counts = {s: len((await db.scalars(select(KbGap.id).where(KbGap.status == s))).all()) for s in ("open", "answered", "rejected")}
        return {"items": items, "counts": counts}

    @app.post("/api/staff/kb/gaps/{gap_id}/answer", tags=["knowledge base"])
    async def answer(gap_id: uuid.UUID, body: AnswerBody, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        staff(current)
        limit.check(request, "kb-answer", str(current.user.id))
        text = mask_question(body.answer_text.strip())  # the same personal-data cleaning as for questions
        published = None
        async with database.session() as db:
            gap = await gap_or_404(db, gap_id)
            if gap.status != "open":
                raise ApiError(409, "already_closed", "На этот вопрос уже ответили или его отклонили.")
            gap.status, gap.answer_text, gap.answered_at = "answered", text, utcnow()
            gap.answered_by = current.user.display_name
            if body.publish:
                published = await publish_answer(db, gap.question_masked, text)
            await db.commit()
            published_id = published.id if published else None
        retriever = getattr(app.state, "kb_retriever", None)
        if published_id and retriever is not None:
            giga = retriever.embedder
            if giga is not None and retriever.vectors:
                # the base already has vectors: compute only this fragment's one; failure leaves it for BM25
                try:
                    async with database.session() as db:
                        chunk = await db.get(KbChunk, published_id)
                        vector = (await giga.embed([chunk.text]))[0]
                        chunk.embedding, chunk.embedding_model = pack_vector(vector), giga.embed_model
                        await db.commit()
                except Exception:
                    pass
            await retriever.reload(database)
        return {"id": str(gap_id), "status": "answered", "published": published_id is not None}

    @app.post("/api/staff/kb/gaps/{gap_id}/reject", tags=["knowledge base"])
    async def reject(gap_id: uuid.UUID, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        staff(current)
        limit.check(request, "kb-answer", str(current.user.id))
        async with database.session() as db:
            gap = await gap_or_404(db, gap_id)
            if gap.status != "open":
                raise ApiError(409, "already_closed", "На этот вопрос уже ответили или его отклонили.")
            gap.status, gap.answered_by, gap.answered_at = "rejected", current.user.display_name, utcnow()
            await db.commit()
        return {"id": str(gap_id), "status": "rejected"}
