"""Hybrid search over the knowledge base: BM25 + vectors, merged by RRF.

BM25 catches exact terms and numbers («форма № 04», «ИУП»); vectors catch
rephrasings («как не потерять стипендию»). Reciprocal rank fusion needs no
score normalisation across the two scales.

The decision «answer or refuse» is NOT taken from the RRF score: RRF always
returns the best of what exists, even when the base has no answer. It is
taken by is_confident() from the top-1 cosine and the share of query terms
found in the top-1 fragment, with thresholds in thresholds.json.

Without GigaChat (no key, 402, breaker open, timeout) the search runs on BM25
only and says so in result.mode; nothing is raised to the caller.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

from ..textsearch import BM25, tokens
from .store import active_chunks, unpack_vector

RRF_K = 60
POOL = 20
THRESHOLDS = Path(__file__).with_name("thresholds.json")
QUERY_TIMEOUT = 5.0
# «см. п. 5.2 Положения о стипендиальном обеспечении (док. 04)», «п. 5.1 этого Положения (док. 01)»
REFERENCE = re.compile(r"п\.\s*(\d+(?:\.\d+)+)[^()]{0,160}?\(док\.\s*([\w-]+)\)")
# «… с Положением … (док. 01) применяется срок, установленный п. 5.1 этого Положения»
REFERENCE_BACK = re.compile(r"\(док\.\s*([\w-]+)\)[^()]{0,120}?п\.\s*(\d+(?:\.\d+)+)")
log = logging.getLogger("hse_schedule.assistant.kb")


@dataclass(frozen=True)
class Fragment:
    id: uuid.UUID
    doc_id: str
    title: str
    section_path: str
    page: int | None
    kind: str
    text: str
    priority: int
    audience: str

    @property
    def body(self) -> str:
        """The fragment without the «[Document › section]» context prefix."""
        first, _, rest = self.text.partition("\n")
        return rest if first.startswith("[") and rest else self.text


@dataclass
class Hit:
    fragment: Fragment
    score: float
    bm25: float = 0.0
    cosine: float | None = None
    reference: bool = False  # added because a found fragment points to it, not found by the search itself
    referenced_by: uuid.UUID | None = None  # the fragment whose text points to this one


@dataclass
class SearchResult:
    hits: list[Hit]
    mode: str  # hybrid | bm25_only | vector_only
    top_cosine: float | None = None
    top_bm25: float = 0.0
    term_coverage: float = 0.0


@dataclass
class _State:
    fragments: list[Fragment] = field(default_factory=list)
    bm25: BM25 | None = None
    matrix: np.ndarray | None = None  # L2-normalised rows; zeros where a fragment has no vector
    has_vector: np.ndarray | None = None
    model: str | None = None


def load_thresholds(path: Path = THRESHOLDS) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def is_confident(result: SearchResult, thresholds: dict | None = None) -> bool:
    """Answer only when the best fragment really covers the question."""
    t = thresholds or load_thresholds()
    if not result.hits:
        return False
    if result.mode in ("hybrid", "vector_only") and result.top_cosine is not None:
        rule = t["hybrid"]
        return result.top_cosine >= rule["min_cosine"] and result.term_coverage >= rule["min_term_coverage"]
    rule = t.get("bm25_rewrite", t["bm25_only"]) if result.mode == "bm25_rewrite" else t["bm25_only"]
    return result.top_bm25 >= rule["min_bm25"] and result.term_coverage >= rule["min_term_coverage"]


class Retriever:
    def __init__(self, embedder=None) -> None:
        self.embedder = embedder  # GigaChat or a test stub with embed(texts, model) and embed_model
        self._state = _State()

    @property
    def size(self) -> int:
        return len(self._state.fragments)

    @property
    def vectors(self) -> int:
        state = self._state
        return int(state.has_vector.sum()) if state.has_vector is not None else 0

    async def load(self, session) -> None:
        """Read active fragments and swap the whole state at once (searches in flight keep the old one)."""
        rows = await active_chunks(session)
        fragments = [Fragment(id=r.id, doc_id=r.document.doc_id, title=r.document.title, section_path=r.section_path,
                              page=r.page, kind=r.kind, text=r.text, priority=r.document.priority,
                              audience=r.document.audience) for r in rows]
        model = self.embedder.embed_model if self.embedder is not None else None
        vectors = [unpack_vector(r.embedding) if r.embedding is not None and (model is None or r.embedding_model == model) else None
                   for r in rows]
        dims = {len(v) for v in vectors if v is not None}
        matrix = has_vector = None
        if len(dims) == 1:
            dim = dims.pop()
            matrix = np.zeros((len(rows), dim), dtype=np.float32)
            has_vector = np.zeros(len(rows), dtype=bool)
            for i, vector in enumerate(vectors):
                if vector is not None:
                    norm = float(np.linalg.norm(vector))
                    if norm:
                        matrix[i] = vector / norm
                        has_vector[i] = True
        self._state = _State(fragments=fragments, bm25=BM25([f.text for f in fragments]) if fragments else None,
                             matrix=matrix, has_vector=has_vector, model=model)

    async def reload(self, database) -> None:
        async with database.session() as session:
            await self.load(session)

    async def _query_vector(self, query: str) -> np.ndarray | None:
        if self.embedder is None:
            return None
        text = query
        if (self.embedder.embed_model or "").lower().startswith("embeddingsgigar"):
            # EmbeddingsGigaR: an instruction before the query (documentation), documents go without it
            text = f"Дан вопрос, необходимо найти абзац текста с ответом\nвопрос: {query}"
        try:
            vector = (await asyncio.wait_for(self.embedder.embed([text]), timeout=QUERY_TIMEOUT))[0]
        except Exception as error:  # no key, 402, breaker, timeout: fall back to BM25
            log.info("query embedding unavailable: %s", type(error).__name__)
            return None
        vector = np.asarray(vector, dtype=np.float32)
        norm = float(np.linalg.norm(vector))
        return vector / norm if norm else None

    async def search(self, query: str, *, audience: set[str] | None = None, k: int = 5, mode: str = "hybrid",
                     expansion: str | None = None) -> SearchResult:
        """mode: hybrid (default), bm25 or vector — the last two exist for the evaluation.

        expansion: terms of the regulations for the same question (from rewrite_query); BM25 runs
        on the question and on the terms alone, and both rankings join the RRF fusion.
        """
        state = self._state
        if not state.fragments:
            return SearchResult(hits=[], mode="bm25_only")
        allowed = [i for i, f in enumerate(state.fragments)
                   if audience is None or f.audience == "all" or f.audience in audience]
        bm25_all = state.bm25.scores(query) if mode != "vector" else [0.0] * len(state.fragments)
        bm25_rank = sorted((i for i in allowed if bm25_all[i] > 0), key=lambda i: -bm25_all[i])[:POOL]
        expanded_all: list[float] | None = None
        expanded_rank: list[int] = []
        if expansion and expansion.strip() and mode != "vector":
            expanded_all = state.bm25.scores(expansion)  # the terms alone: a second, independent view of the question
            expanded_rank = sorted((i for i in allowed if expanded_all[i] > 0), key=lambda i: -expanded_all[i])[:POOL]

        cosines: np.ndarray | None = None
        vector_rank: list[int] = []
        if mode != "bm25" and state.matrix is not None and state.has_vector is not None and state.has_vector.any():
            q = await self._query_vector(query)
            if q is not None and q.shape[0] == state.matrix.shape[1]:
                cosines = state.matrix @ q
                vector_rank = sorted((i for i in allowed if state.has_vector[i]), key=lambda i: -float(cosines[i]))[:POOL]

        if mode == "vector" and not vector_rank:
            return SearchResult(hits=[], mode="vector_only")
        used = "hybrid" if vector_rank and mode == "hybrid" else ("vector_only" if mode == "vector" else "bm25_only")
        rankings = [bm25_rank] if used == "bm25_only" else [vector_rank] if used == "vector_only" else [bm25_rank, vector_rank]
        if expanded_rank and used != "vector_only":
            rankings.append(expanded_rank)
            if used == "bm25_only":
                used = "bm25_rewrite"
        fused: dict[int, float] = {}
        for ranking in rankings:
            for place, i in enumerate(ranking, start=1):
                fused[i] = fused.get(i, 0.0) + 1.0 / (RRF_K + place)
        # equal fused score → the document with the higher priority (smaller number) wins
        order = sorted(fused, key=lambda i: (-round(fused[i], 9), state.fragments[i].priority, i))[:k]
        word_score = [max(a, b) for a, b in zip(bm25_all, expanded_all)] if expanded_all else bm25_all
        hits = [Hit(fragment=state.fragments[i], score=fused[i], bm25=word_score[i],
                    cosine=float(cosines[i]) if cosines is not None and state.has_vector[i] else None) for i in order]
        result = SearchResult(hits=hits, mode=used)
        if hits:
            top = hits[0]
            if used == "bm25_rewrite":
                # Found live: «нейросетями в курсовой» put a weak clause first (it got votes from both
                # rankings for «курсовая»), while the strong match from the rewrite was lower. With
                # rewriting, confidence comes from the strongest word match among the returned hits.
                top = max(hits, key=lambda h: h.bm25)
            result.top_bm25 = top.bm25
            result.top_cosine = top.cosine
            terms = set(tokens(query))
            present = set(tokens(top.fragment.text))
            result.term_coverage = len(terms & present) / len(terms) if terms else 0.0
            if expansion:  # the regulation's words for the question count as its words too
                extra = set(tokens(expansion))
                if extra:
                    result.term_coverage = max(result.term_coverage, len(extra & present) / len(extra))
        return result


    def expand_references(self, hits: list[Hit], limit: int = 5) -> list[Hit]:
        """Add fragments the found ones explicitly point to («п. 5.2 … (док. 07)»), right after them.

        A rule that says «see clause 5.1 of document 01» is only half an answer;
        the referenced clause goes to the answerer together with it.
        """
        from .chunker import matches_section

        state = self._state
        pending = list(hits)
        placed: set = set()
        out: list[Hit] = []
        while pending:
            hit = pending.pop(0)
            if hit.fragment.id in placed:
                continue
            out.append(hit)
            placed.add(hit.fragment.id)
            refs = REFERENCE.findall(hit.fragment.body) + [(n, d) for d, n in REFERENCE_BACK.findall(hit.fragment.body)]
            for number, doc_id in refs:
                target = next((f for f in state.fragments if f.doc_id == doc_id and matches_section(f.section_path, number)), None)
                if target is None or target.id in placed:
                    continue
                # already found lower in the list? move it up, right after the clause that points to it
                found = next((h for h in pending if h.fragment.id == target.id), None)
                if found is not None:
                    pending.remove(found)
                out.append(Hit(fragment=target, score=hit.score, bm25=found.bm25 if found else 0.0,
                               cosine=found.cosine if found else None, reference=True, referenced_by=hit.fragment.id))
                placed.add(target.id)
        return out[:limit]
