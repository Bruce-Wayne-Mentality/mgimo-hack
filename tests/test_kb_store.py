"""Knowledge base storage: vectors, fragment replacement, active filter, cascade.

SQLite by default; with TEST_DATABASE_URL the same tests run on PostgreSQL (CI).
"""

from __future__ import annotations

import asyncio
import os
import shutil
import tempfile
import unittest
from pathlib import Path

import numpy as np
from sqlalchemy import func, select, text

from hse_schedule.assistant.kb.models import KbChunk, KbDocument
from hse_schedule.assistant.kb.store import ChunkData, active_chunks, pack_vector, replace_chunks, unpack_vector, upsert_document
from hse_schedule.db import Database
from hse_schedule.migrate import upgrade
from tests.test_auth import reset_postgres


def chunk(text: str, n: int = 0) -> ChunkData:
    return ChunkData(text=text, section_path=f"п. {n}", kind="clause", tokens=len(text.split()), content_hash=f"h-{text}")


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(self.temporary / 'kb.sqlite3').as_posix()}"
        if os.environ.get("TEST_DATABASE_URL"):
            reset_postgres(self.url)
        upgrade(self.url)
        self.database = Database(self.url, pooled=False)
        self.addCleanup(lambda: asyncio.run(self.database.dispose()))

    async def _document(self, db, doc_id: str, status: str = "active") -> KbDocument:
        return await upsert_document(db, doc_id=doc_id, title=f"Документ {doc_id}", kind="regulation", version="1",
                                     status=status, priority=2, audience="all", source_path=f"pdfs/{doc_id}.pdf",
                                     content_hash="x" * 64)

    def test_vector_round_trip(self):
        vector = [0.25, -1.5, 3.0, 1e-7]
        data = pack_vector(vector)
        self.assertEqual(len(data), 16)  # float32
        np.testing.assert_allclose(unpack_vector(data), vector, rtol=1e-6)
        self.assertEqual(unpack_vector(data).dtype, np.float32)

    def test_replace_chunks_leaves_no_duplicates_and_keeps_unchanged_vectors(self):
        async def run():
            async with self.database.session() as db:
                document = await self._document(db, "01")
                rows = await replace_chunks(db, document, [chunk("первый", 1), chunk("второй", 2)])
                rows[0].embedding, rows[0].embedding_model = pack_vector([1.0, 2.0]), "Embeddings"
                await db.commit()
            async with self.database.session() as db:
                document = await db.scalar(select(KbDocument).where(KbDocument.doc_id == "01"))
                await replace_chunks(db, document, [chunk("первый", 1), chunk("новый", 2), chunk("третий", 3)])
                await db.commit()
            async with self.database.session() as db:
                rows = (await db.scalars(select(KbChunk).order_by(KbChunk.ord))).all()
                return [(r.ord, r.text, r.embedding is not None) for r in rows]

        self.assertEqual(asyncio.run(run()), [(0, "первый", True), (1, "новый", False), (2, "третий", False)])

    def test_upsert_updates_in_place(self):
        async def run():
            async with self.database.session() as db:
                await self._document(db, "02")
                await self._document(db, "02", status="superseded")
                await db.commit()
                return await db.scalar(select(func.count()).select_from(KbDocument))

        self.assertEqual(asyncio.run(run()), 1)

    def test_active_chunks_skip_superseded_documents(self):
        async def run():
            async with self.database.session() as db:
                await replace_chunks(db, await self._document(db, "04"), [chunk("редакция два")])
                await replace_chunks(db, await self._document(db, "04_old", status="superseded"), [chunk("редакция один")])
                await db.commit()
                rows = await active_chunks(db)
                return [(r.document.doc_id, r.text) for r in rows]

        self.assertEqual(asyncio.run(run()), [("04", "редакция два")])

    def test_deleting_a_document_deletes_its_chunks(self):
        async def run():
            async with self.database.session() as db:
                await replace_chunks(db, await self._document(db, "05"), [chunk("а"), chunk("б")])
                await replace_chunks(db, await self._document(db, "06"), [chunk("в")])
                await db.commit()
            async with self.database.session() as db:
                document = await db.scalar(select(KbDocument).where(KbDocument.doc_id == "05"))
                await db.delete(document)
                await db.commit()
                if self.url.startswith("postgres"):  # the schema-level cascade, without the ORM
                    await db.execute(text("DELETE FROM kb_documents WHERE doc_id = '06'"))
                    await db.commit()
                return await db.scalar(select(func.count()).select_from(KbChunk))

        self.assertEqual(asyncio.run(run()), 0 if self.url.startswith("postgres") else 1)


if __name__ == "__main__":
    unittest.main()
