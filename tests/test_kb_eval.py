"""Regression guard for retrieval quality (BM25 only, no network).

Numbers recorded in docs/rag/EVAL.md: hit@5 = 0.92 and 3 of 3 correct refusals.
The guard allows one question of slack on hit@5 (0.92 − 1/12 ≈ 0.83).
"""

from __future__ import annotations

import asyncio
import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path

from hse_schedule.assistant.kb import evaluation
from hse_schedule.assistant.kb.ingest import ingest_manifest
from hse_schedule.assistant.kb.retriever import Retriever, is_confident, load_thresholds
from hse_schedule.db import Database
from hse_schedule.migrate import upgrade

DATA = Path(__file__).resolve().parents[1] / "rag_test_data"
HAS_KB_EXTRAS = importlib.util.find_spec("pdfplumber") is not None and importlib.util.find_spec("bs4") is not None


@unittest.skipUnless(HAS_KB_EXTRAS, "pdfplumber/beautifulsoup4 not installed (pip install -e .[kb])")
class RetrievalRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = Path(tempfile.mkdtemp())
        url = cls.url = f"sqlite:///{(cls.temporary / 'eval.sqlite3').as_posix()}"
        upgrade(url)

        async def run():
            database = Database(url, pooled=False)
            async with database.session() as db:
                await ingest_manifest(db, DATA / "manifest.json")
            retriever = Retriever(None)
            await retriever.reload(database)
            rows = await evaluation.run_mode(retriever, evaluation.load_questions(DATA / "questions.json"), "bm25")
            await database.dispose()
            return rows

        cls.metrics = evaluation.metrics(asyncio.run(run()), load_thresholds())

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.temporary, ignore_errors=True)

    def test_answer_check_compares_numbers_not_word_forms(self):
        self.assertTrue(evaluation.answer_ok("ГАС — 5400 рублей в месяц", {"must_contain": ["5400 руб."]}))
        self.assertFalse(evaluation.answer_ok("ГАС — 15400 рублей", {"must_contain": ["5400 руб."]}))
        self.assertTrue(evaluation.answer_ok("нужна «декларация об использовании ИИ»", {"must_contain": ["Декларация об использовании ИИ"]}))
        self.assertFalse(evaluation.answer_ok("нужна справка", {"must_contain": ["086/у"]}))
        # word forms count, missing facts do not; numbers written as words do not count
        self.assertTrue(evaluation.answer_ok("укажите в декларации об использовании ИИ", {"must_contain": ["Декларация об использовании ИИ"]}))
        self.assertFalse(evaluation.answer_ok("не более двух раз", {"must_contain": ["не более двух раз", "комиссией"]}))
        self.assertFalse(evaluation.answer_ok("с первого числа", {"must_contain": ["с 1 числа месяца"]}))

    def test_live_paraphrase_with_its_recorded_rewrite_is_answered(self):
        """Refused live on 17.11.2026 before the fix; the expansion is the one GigaChat returned then."""
        async def run():
            database = Database(self.url, pooled=False)
            retriever = Retriever(None)
            await retriever.reload(database)
            result = await retriever.search("Можно ли пользоваться нейросетями в курсовой?", k=5,
                                            expansion="генеративные инструменты искусственный интеллект нейроассистенты умные помощники")
            await database.dispose()
            return result

        result = asyncio.run(run())
        self.assertIn("07", {h.fragment.doc_id for h in result.hits})
        self.assertTrue(is_confident(result, load_thresholds()))

    def test_hit_at_5_does_not_drop(self):
        self.assertGreaterEqual(self.metrics["hit@5"], 0.83)

    def test_every_unanswerable_question_is_refused(self):
        self.assertEqual((self.metrics["refused"], self.metrics["refusals_total"]), (3, 3))

    def test_answerable_questions_pass_the_threshold(self):
        self.assertGreaterEqual(self.metrics["accepted"], 11)


if __name__ == "__main__":
    unittest.main()
