"""kb-build / kb-embed / kb-stats on a temporary SQLite, GigaChat replaced by a stub."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import importlib.util
import io
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from sqlalchemy import func, select

from hse_schedule import cli
from hse_schedule.assistant.kb import commands
from hse_schedule.assistant.kb.models import KbChunk, KbDocument
from hse_schedule.db import Database

ROOT = Path(__file__).resolve().parents[1]
HAS_KB_EXTRAS = importlib.util.find_spec("pdfplumber") is not None and importlib.util.find_spec("bs4") is not None


def fake_vector(text: str, dim: int = 8) -> list[float]:
    digest = hashlib.sha256(text.encode("utf-8")).digest()
    return [b / 255 for b in digest[:dim]]


class FakeGiga:
    embed_model = "Embeddings"

    def __init__(self) -> None:
        self.calls = 0
        self.texts = 0

    async def embed(self, texts: list[str], model: str | None = None) -> list[list[float]]:
        self.calls += 1
        self.texts += len(texts)
        return [fake_vector(t) for t in texts]


@unittest.skipUnless(HAS_KB_EXTRAS, "pdfplumber/beautifulsoup4 not installed (pip install -e .[kb])")
class KbCliTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.url = f"sqlite:///{(self.temporary / 'kb.sqlite3').as_posix()}"
        commands.PAUSE = 0

    def run_cli(self, *args: str) -> str:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = cli.main([*args, "--database-url", self.url])
        self.assertEqual(code, 0, out.getvalue())
        return out.getvalue()

    def counts(self) -> tuple[int, int, int]:
        async def run():
            database = Database(self.url, pooled=False)
            async with database.session() as db:
                documents = await db.scalar(select(func.count()).select_from(KbDocument))
                chunks = await db.scalar(select(func.count()).select_from(KbChunk))
                embedded = await db.scalar(select(func.count()).select_from(KbChunk).where(KbChunk.embedding.is_not(None)))
            await database.dispose()
            return documents, chunks, embedded

        return asyncio.run(run())

    def test_build_is_idempotent(self):
        self.run_cli("kb-build", "--manifest", str(ROOT / "rag_test_data" / "manifest.json"))
        first = self.counts()
        self.assertEqual(first[0], 14)
        self.assertGreater(first[1], 100)
        output = self.run_cli("kb-build", "--manifest", str(ROOT / "rag_test_data" / "manifest.json"))
        self.assertIn("переиндексировано: 0", output)
        self.assertEqual(self.counts(), first)

    def test_embed_fills_vectors_once(self):
        self.run_cli("kb-build", "--manifest", str(ROOT / "rag_test_data" / "manifest.json"))
        giga = FakeGiga()
        with mock.patch("hse_schedule.gigachat.GigaChat.from_env", return_value=giga):
            self.run_cli("kb-embed")
            documents, chunks, embedded = self.counts()
            superseded = self._superseded_chunks()
            self.assertEqual(embedded, chunks - superseded)  # superseded editions are never searched
            self.assertEqual(giga.texts, chunks - superseded)
            calls = giga.calls
            self.run_cli("kb-embed")
            self.assertEqual(giga.calls, calls)  # second run: nothing to do, no requests
        stats = self.run_cli("kb-stats")
        self.assertIn(f"с эмбеддингом: {embedded}", stats)

    def test_embed_without_a_key_explains_and_succeeds(self):
        self.run_cli("kb-build", "--manifest", str(ROOT / "rag_test_data" / "manifest.json"))
        with mock.patch("hse_schedule.gigachat.GigaChat.from_env", return_value=None):
            output = self.run_cli("kb-embed")
        self.assertIn("Ключ не задан", output)

    def _superseded_chunks(self) -> int:
        async def run():
            database = Database(self.url, pooled=False)
            async with database.session() as db:
                value = await db.scalar(select(func.count()).select_from(KbChunk).join(KbDocument)
                                        .where(KbDocument.status == "superseded"))
            await database.dispose()
            return value

        return asyncio.run(run())


if __name__ == "__main__":
    unittest.main()
