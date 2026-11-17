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
from hse_schedule.assistant.kb.retriever import Retriever, load_thresholds
from hse_schedule.db import Database
from hse_schedule.migrate import upgrade

DATA = Path(__file__).resolve().parents[1] / "rag_test_data"
HAS_KB_EXTRAS = importlib.util.find_spec("pdfplumber") is not None and importlib.util.find_spec("bs4") is not None


@unittest.skipUnless(HAS_KB_EXTRAS, "pdfplumber/beautifulsoup4 not installed (pip install -e .[kb])")
class RetrievalRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = Path(tempfile.mkdtemp())
        url = f"sqlite:///{(cls.temporary / 'eval.sqlite3').as_posix()}"
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

    def test_hit_at_5_does_not_drop(self):
        self.assertGreaterEqual(self.metrics["hit@5"], 0.83)

    def test_every_unanswerable_question_is_refused(self):
        self.assertEqual((self.metrics["refused"], self.metrics["refusals_total"]), (3, 3))

    def test_answerable_questions_pass_the_threshold(self):
        self.assertGreaterEqual(self.metrics["accepted"], 11)


if __name__ == "__main__":
    unittest.main()
