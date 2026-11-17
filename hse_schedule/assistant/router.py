"""K4 HTTP API: ask, hand off to a staff member, suggestions."""

from __future__ import annotations

import asyncio
from datetime import timedelta

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ..accounts.router import ApiError
from ..accounts.service import CurrentSession
from ..gigachat import GigaChat
from ..ratelimit import RateLimiter
from . import engine
from .kb import rag_enabled
from .kb.answerer import answer_from_kb, mask_question
from .kb.retriever import Retriever


class Turn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: StrictStr = Field(pattern="^(user|assistant)$")
    text: StrictStr = Field(max_length=2000)


class AskBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: StrictStr = Field(min_length=1, max_length=1000)
    about: StrictStr | None = Field(default=None, max_length=200)
    intent: StrictStr | None = Field(default=None, max_length=32)


class HandoffBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    summary: StrictStr = Field(min_length=3, max_length=1000)
    transcript: list[Turn] = Field(default_factory=list, max_length=20)


def register_assistant_routes(app: FastAPI, academics, requests_service, schedule, database=None) -> None:
    require_session = app.state.require_session
    limit = RateLimiter(limit=30, window=60)
    giga = GigaChat.from_env()
    retriever = Retriever(giga)  # vectors only when the base has them; otherwise BM25 without calling GigaChat
    app.state.kb_retriever = retriever
    loaded = {"done": False}
    lock = asyncio.Lock()

    async def knowledge_base() -> Retriever | None:
        if database is None:
            return None
        if not loaded["done"]:
            async with lock:
                if not loaded["done"]:
                    await retriever.reload(database)
                    loaded["done"] = True
        return retriever if retriever.size else None

    from ..student_requests.router import summary_payload

    async def context(current: CurrentSession) -> engine.StudentContext:
        user = current.user
        overview = await academics.overview(user)
        today = engine.datetime.now(engine.MOSCOW).date()
        try:
            lessons = await asyncio.to_thread(schedule.get_schedule, user.student.email, today, today + timedelta(days=6))
            lessons = [lesson.to_dict() for lesson in lessons]
        except Exception:
            lessons = []
        requests = [summary_payload(r) for r in await requests_service.list_own(user)]
        first = user.display_name.split()[0] if user.display_name else ""
        return engine.StudentContext(first_name=first, overview=overview, lessons=lessons, requests=requests, today=today)

    def student(current: CurrentSession) -> None:
        if current.user.role != "student" or current.user.student is None:
            raise ApiError(403, "forbidden", "Ассистент доступен студентам.")

    @app.get("/api/assistant", tags=["assistant"])
    async def info(current: CurrentSession = Depends(require_session)) -> dict:
        student(current)
        return {"disclaimer": engine.DISCLAIMER, "suggestions": engine.SUGGESTIONS,
                "engine": "gigachat" if giga else "rules",
                "engine_label": "GigaChat + база правил" if giga else "Демо-режим: база правил и ваши данные (GigaChat подключается ключом на сервере)"}

    @app.post("/api/assistant/ask", tags=["assistant"])
    async def ask(body: AskBody, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        student(current)
        limit.check(request, "assistant", str(current.user.id))
        ctx = await context(current)
        names = (current.user.display_name or "").split()
        reply = engine.answer(body.message, ctx, about=body.about, intent=body.intent, kb=rag_enabled() and database is not None)
        if reply.kind == "kb_search":
            kb = await knowledge_base()
            if kb is None:  # empty or missing base: the 15 built-in rules are the reserve
                reply = engine.answer(body.message, ctx, about=body.about, intent=body.intent)
            else:
                found = await answer_from_kb(body.message, kb, giga, database, names=names, handoff_text=body.message)
                return {"text": found.text, "kind": found.kind, "sources": found.sources, "actions": reply.actions + found.actions,
                        "facts": [], "engine": "rag", "rag_mode": found.mode}
        data = reply.to_dict()
        data["engine"] = "rules"
        # Only rule texts are rephrased, and only with the masked question: answers «about me»
        # carry grades, requests and the schedule, which never leave the server.
        if giga and reply.kind == "rule":
            try:
                text = await asyncio.wait_for(giga.rephrase(mask_question(body.message, names), reply.text), timeout=9)
                if text:
                    data["text"], data["engine"] = text, "gigachat"
            except Exception:
                data["engine"] = "rules-fallback"
        return data

    @app.post("/api/assistant/handoff", status_code=201, tags=["assistant"])
    async def handoff(body: HandoffBody, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        student(current)
        limit.check(request, "assistant-handoff", str(current.user.id))
        lines = [f"{'Студент' if t.role == 'user' else 'Ассистент'}: {t.text.strip()[:300]}" for t in body.transcript[-6:]]
        dialogue = "\n".join(lines)
        payload = {"question": body.summary.strip()[:1000], "dialogue": dialogue[:1000]} if dialogue else {"question": body.summary.strip()[:1000]}
        created, _ = await requests_service.create(current.user, "QUESTION", payload, None)
        return {"id": str(created.id), "number": created.number, "link": f"/requests/{created.id}"}
