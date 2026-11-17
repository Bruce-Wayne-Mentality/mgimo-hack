"""Hybrid retriever on a tiny artificial corpus with a stub embedder (no network)."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
import unittest
from pathlib import Path

from hse_schedule.assistant.kb.retriever import Retriever, SearchResult, is_confident
from hse_schedule.assistant.kb.store import ChunkData, pack_vector, replace_chunks, upsert_document
from hse_schedule.db import Database
from hse_schedule.gigachat import GigaChatUnavailable
from hse_schedule.migrate import upgrade

QUERY = [1.0, 0.0, 0.0]


class StubEmbedder:
    embed_model = "Stub"

    def __init__(self, *, fail: bool = False, delay: float = 0.0) -> None:
        self.fail, self.delay, self.calls = fail, delay, 0

    async def embed(self, texts, model=None):
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.fail:
            raise GigaChatUnavailable("402")
        return [QUERY for _ in texts]


def c(text: str, n: int) -> ChunkData:
    return ChunkData(text=text, section_path=f"п. {n}", kind="clause", tokens=len(text.split()), content_hash=f"h{n}-{text}")


class RetrieverTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.url = f"sqlite:///{(self.temporary / 'r.sqlite3').as_posix()}"
        upgrade(self.url)
        self.database = Database(self.url, pooled=False)
        self.addCleanup(lambda: asyncio.run(self.database.dispose()))
        asyncio.run(self._fill())

    async def _doc(self, db, doc_id, *, status="active", audience="all", priority=2):
        return await upsert_document(db, doc_id=doc_id, title=f"Документ {doc_id}", kind="regulation", version="1",
                                     status=status, priority=priority, audience=audience, source_path=doc_id, content_hash="x")

    async def _fill(self):
        async with self.database.session() as db:
            rows = await replace_chunks(db, await self._doc(db, "01"), [
                c("стипендия выплачивается ежемесячно на карту", 1),            # A: BM25 rank 2 + vector rank 2
                c("стипендия выплата стипендия выплата размер стипендии", 2),   # B: BM25 rank 1, no vector
                c("академический отпуск предоставляется на два года", 3),        # C: vector rank 1, no shared words
            ])
            rows[0].embedding, rows[0].embedding_model = pack_vector([0.9, 0.43, 0.0]), "Stub"
            rows[2].embedding, rows[2].embedding_model = pack_vector([0.95, 0.0, 0.31]), "Stub"
            await replace_chunks(db, await self._doc(db, "04_old", status="superseded"), [c("старая редакция стипендия выплата", 4)])
            await replace_chunks(db, await self._doc(db, "02", audience="foreign"), [c("миграционный учёт иностранных граждан", 5)])
            await db.commit()

    def retriever(self, embedder=None) -> Retriever:
        r = Retriever(embedder)
        asyncio.run(r.reload(self.database))
        return r

    def test_rrf_lifts_a_fragment_found_by_both_methods(self):
        result = asyncio.run(self.retriever(StubEmbedder()).search("стипендия выплата"))
        self.assertEqual(result.mode, "hybrid")
        self.assertEqual(result.hits[0].fragment.section_path, "п. 1")
        self.assertAlmostEqual(result.hits[0].score, 2 / 62)
        self.assertIsNotNone(result.top_cosine)

    def test_superseded_edition_is_never_returned(self):
        result = asyncio.run(self.retriever().search("старая редакция стипендия выплата", k=10))
        self.assertTrue(result.hits)
        self.assertNotIn("04_old", {h.fragment.doc_id for h in result.hits})

    def test_audience_filter(self):
        r = self.retriever()
        everyone = asyncio.run(r.search("миграционный учёт иностранных граждан"))
        self.assertEqual(everyone.hits[0].fragment.doc_id, "02")
        bachelors = asyncio.run(r.search("миграционный учёт иностранных граждан", audience={"bachelor"}))
        self.assertNotIn("02", {h.fragment.doc_id for h in bachelors.hits})

    def test_without_gigachat_search_is_bm25_only_and_does_not_raise(self):
        for embedder in (None, StubEmbedder(fail=True)):
            with self.subTest(embedder=embedder):
                result = asyncio.run(self.retriever(embedder).search("стипендия выплата"))
                self.assertEqual(result.mode, "bm25_only")
                self.assertEqual(result.hits[0].fragment.section_path, "п. 2")
                self.assertIsNone(result.top_cosine)

    def test_reload_does_not_break_a_search_in_flight(self):
        r = self.retriever(StubEmbedder(delay=0.2))

        async def run():
            search = asyncio.create_task(r.search("стипендия выплата"))
            await asyncio.sleep(0.05)
            async with self.database.session() as db:
                from sqlalchemy import select

                from hse_schedule.assistant.kb.models import KbDocument
                document = await db.scalar(select(KbDocument).where(KbDocument.doc_id == "01"))
                await replace_chunks(db, document, [c("совсем другой текст про общежитие", 9)])
                await db.commit()
            await r.reload(self.database)
            return await search

        result = asyncio.run(run())
        self.assertIn("п. 1", {h.fragment.section_path for h in result.hits})  # the old state, whole
        after = asyncio.run(r.search("общежитие"))
        self.assertEqual(after.hits[0].fragment.section_path, "п. 9")

    def test_expansion_finds_the_rule_by_its_own_words(self):
        r = self.retriever()
        plain = asyncio.run(r.search("сколько можно отдыхать от учёбы"))
        self.assertEqual(plain.hits, [])  # no shared words with the rules
        rewritten = asyncio.run(r.search("сколько можно отдыхать от учёбы", expansion="академический отпуск срок"))
        self.assertEqual(rewritten.mode, "bm25_rewrite")
        self.assertEqual(rewritten.hits[0].fragment.section_path, "п. 3")
        self.assertGreater(rewritten.term_coverage, 0.5)  # the regulation's words count as the question's

    def test_rewrite_mode_has_its_own_thresholds(self):
        r = self.retriever()
        result = asyncio.run(r.search("отпуск", expansion="академический отпуск"))
        loose = {"bm25_only": {"min_bm25": 99, "min_term_coverage": 1.0}, "bm25_rewrite": {"min_bm25": 0.1, "min_term_coverage": 0.1},
                 "hybrid": {"min_cosine": 0.5, "min_term_coverage": 0.3}}
        self.assertTrue(is_confident(result, loose))
        self.assertFalse(is_confident(result, {**loose, "bm25_rewrite": {"min_bm25": 99, "min_term_coverage": 1.0}}))

    def test_term_coverage_and_confidence(self):
        r = self.retriever()
        result = asyncio.run(r.search("стипендия выплата"))
        self.assertEqual(result.term_coverage, 1.0)
        thresholds = {"bm25_only": {"min_bm25": 0.1, "min_term_coverage": 0.5}, "hybrid": {"min_cosine": 0.5, "min_term_coverage": 0.3}}
        self.assertTrue(is_confident(result, thresholds))
        miss = asyncio.run(r.search("парковка у корпуса"))
        self.assertFalse(is_confident(miss, thresholds))
        self.assertFalse(is_confident(SearchResult(hits=[], mode="bm25_only"), thresholds))


if __name__ == "__main__":
    unittest.main()
