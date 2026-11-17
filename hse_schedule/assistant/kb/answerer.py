"""Answers from the knowledge base with sources, server-side checks and an honest fallback.

Order:
a) personal data out of the question (the red button's masker plus long digit runs);
b) search; not confident → refusal «В правилах ответа нет», a handoff to the
   deanery and a KbGap row with the masked question only;
c) GigaChat formulates the answer from at most five fragments in <source> tags;
d) the server checks the answer itself: cited ids are real, every number in the
   answer occurs in the cited fragments, no links or commands from nowhere;
e) anything fails (or GigaChat is absent) → the exact top fragment as a quote.

GigaChat exceptions never leave this module. The log gets kind, mode, time and
fragment ids — never the question or the answer.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import OrderedDict
from dataclasses import dataclass, field

from ...redbutton.stage1 import mask_pdn
from . import prompts
from .models import KbGap
from .retriever import Hit, Retriever, is_confident

log = logging.getLogger("hse_schedule.assistant.kb")
REFUSAL = "В правилах ответа нет. Можно задать вопрос деканату — сотрудник ответит в «Заявках»."
LONG_DIGITS = re.compile(r"\b\d[\d\s-]{6,}\d\b")  # record book, passport, card numbers
NUMBER = re.compile(r"\d+(?:[.,]\d+)*")
LINK = re.compile(r"(https?://\S+|www\.\S+|\S+@\S+\.\w+|/[a-z][\w/-]{2,})", re.IGNORECASE)
MAX_ANSWER = 900
TIMEOUT = 12.0
REWRITE_TIMEOUT = 6.0
_rewrites: OrderedDict[str, str] = OrderedDict()  # masked question → terms; the same question costs one call


async def rewrite_query(gigachat, masked: str) -> str | None:
    """The regulations' words for a (masked) question, for BM25. None when GigaChat is absent or fails."""
    if gigachat is None or not masked.strip():
        return None
    if masked in _rewrites:
        _rewrites.move_to_end(masked)
        return _rewrites[masked]
    try:
        result = await asyncio.wait_for(
            gigachat.chat_json(prompts.REWRITE_SYSTEM, f"Вопрос студента: {masked}", prompts.REWRITE_SCHEMA,
                               name="terms", temperature=0.0, max_tokens=120),
            timeout=REWRITE_TIMEOUT)
        terms = result.data.get("terms") if isinstance(result.data, dict) else None
        if not isinstance(terms, list):
            return None
        text = " ".join(t.strip() for t in terms if isinstance(t, str) and t.strip())[:400]
    except Exception:  # unavailable, timeout, invalid answer: search without the terms
        return None
    _rewrites[masked] = text
    if len(_rewrites) > 512:
        _rewrites.popitem(last=False)
    return text or None


@dataclass
class KbReply:
    text: str
    kind: str  # kb_answer | kb_extract | kb_refusal
    sources: list[dict] = field(default_factory=list)
    confidence: float = 0.0
    mode: str = "bm25_only"
    actions: list[dict] = field(default_factory=list)


def mask_question(question: str, names: list[str] = ()) -> str:
    return LONG_DIGITS.sub("[НОМЕР]", mask_pdn(question, names=list(names)))


def _source(hit: Hit) -> dict:
    f = hit.fragment
    return {"id": f.doc_id, "doc_id": f.doc_id, "title": f.title, "section_path": f.section_path, "page": f.page,
            "chunk_id": str(f.id), "excerpt": f.body[:700]}


def check_answer(answer: str, used: list[str], sources: dict[str, Hit]) -> str | None:
    """None when the answer passes; otherwise the reason it is rejected."""
    if not answer.strip():
        return "empty"
    if len(answer) > MAX_ANSWER:
        return "too_long"
    if not used:
        return "no_sources"
    if any(chunk_id not in sources for chunk_id in used):
        return "unknown_source"
    # A cited rule that points to another clause («применяется п. 5.1 Положения…») is only half
    # of the answer: the clause it points to must be cited too (conflict and cross-reference traps).
    for hit in sources.values():
        if hit.referenced_by is not None and str(hit.referenced_by) in used and str(hit.fragment.id) not in used:
            return "reference_ignored"
    cited = "\n".join(sources[chunk_id].fragment.text for chunk_id in used)
    cited_flat = cited.replace(" ", "").replace(" ", "")
    for number in NUMBER.findall(answer):
        if number not in cited and number.replace(" ", "") not in cited_flat:
            return "number_not_in_sources"
    for link in LINK.findall(answer):
        if link.rstrip(".,;)") not in cited:
            return "link_not_in_sources"
    return None


def _extract(hits: list[Hit], confidence: float, mode: str) -> KbReply:
    top = hits[0]
    parts = [f"Точная цитата из правил:\n{top.fragment.body}", f"Из документа «{top.fragment.title}», {top.fragment.section_path}."]
    used = [top]
    # a fragment the top one explicitly refers to (added by expand_references) belongs to the same answer
    if len(hits) > 1 and hits[1].reference:
        ref = hits[1]
        parts.append(f"Пункт, на который он ссылается:\n{ref.fragment.body}\nИз документа «{ref.fragment.title}», {ref.fragment.section_path}.")
        used.append(ref)
    return KbReply(text="\n\n".join(parts), kind="kb_extract", sources=[_source(h) for h in used], confidence=confidence, mode=mode)


async def answer_from_kb(question: str, retriever: Retriever, gigachat, database, *, names: list[str] = (),
                         thresholds: dict | None = None, handoff_text: str | None = None) -> KbReply:
    started = time.perf_counter()
    masked = mask_question(question, names)
    expansion = await rewrite_query(gigachat, masked)
    result = await retriever.search(masked, k=5, expansion=expansion)
    confidence = (result.top_cosine if result.top_cosine is not None else result.top_bm25) if result.hits else 0.0
    if not is_confident(result, thresholds):
        top = result.hits[0] if result.hits else None
        async with database.session() as db:
            db.add(KbGap(question_masked=masked[:1000], top_score=float(confidence),
                         top_chunk_id=top.fragment.id if top else None))
            await db.commit()
        log.info("kb reply kind=kb_refusal mode=%s ms=%d", result.mode, int((time.perf_counter() - started) * 1000))
        return KbReply(text=REFUSAL, kind="kb_refusal", confidence=float(confidence), mode=result.mode,
                       actions=[{"kind": "handoff", "label": "Спросить деканат", "summary": (handoff_text or question).strip()[:500]}])

    hits = retriever.expand_references(result.hits, limit=5)
    reply: KbReply | None = None
    reason = "no_gigachat"
    if gigachat is not None:
        by_id = {str(h.fragment.id): h for h in hits}
        user = prompts.user_message(masked, [(str(h.fragment.id), h.fragment.text, h.fragment.priority) for h in hits])
        try:
            answer = await asyncio.wait_for(
                gigachat.chat_json(prompts.SYSTEM, user, prompts.SCHEMA, name="answer", temperature=0.1, max_tokens=700),
                timeout=TIMEOUT)
            data = answer.data if isinstance(answer.data, dict) else {}
            text = data.get("answer") if isinstance(data.get("answer"), str) else ""
            used = [str(x) for x in data.get("used_sources") or [] if isinstance(x, (str, int))]
            if data.get("answerable") is False:
                reason = "model_not_answerable"
            else:
                reason = check_answer(text, used, by_id) or ""
                if not reason:
                    reply = KbReply(text=text.strip(), kind="kb_answer", sources=[_source(by_id[i]) for i in dict.fromkeys(used)],
                                    confidence=float(confidence), mode=result.mode)
        except Exception as error:  # unavailable, blacklist, invalid JSON, timeout — never raised to the student
            reason = type(error).__name__
    if reply is None:
        reply = _extract(hits, float(confidence), result.mode)
    log.info("kb reply kind=%s mode=%s ms=%d chunks=%s fallback=%s", reply.kind, reply.mode,
             int((time.perf_counter() - started) * 1000), ",".join(s["chunk_id"][:8] for s in reply.sources), reason or "-")
    return reply
