"""Chunker on hand-made blocks, and parsers on the real test bench."""

from __future__ import annotations

import importlib.util
import json
import unittest
from pathlib import Path

from hse_schedule.assistant.kb.blocks import Block, table_text
from hse_schedule.assistant.kb.chunker import LIMIT, chunk, count_tokens, matches_section

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "rag_test_data"
HAS_KB_EXTRAS = importlib.util.find_spec("pdfplumber") is not None and importlib.util.find_spec("bs4") is not None


def heading(number: str, title: str) -> Block:
    return Block("heading", f"{number} {title}", number=number, page=1)


def clause(number: str, text: str, page: int = 1) -> Block:
    return Block("clause", f"{number} {text}", number=number, page=page)


class ChunkerTests(unittest.TestCase):
    def test_one_clause_is_one_fragment_and_never_split_in_half(self):
        blocks = [heading("4.", "Пересдачи"), clause("4.1.", "Первый пункт про задолженность."),
                  clause("4.2.", "Второй пункт: не более двух раз, вторая — комиссией.")]
        chunks = chunk(blocks, "Положение")
        self.assertEqual([c.section_path for c in chunks], ["Раздел 4 › п. 4.1", "Раздел 4 › п. 4.2"])
        self.assertIn("не более двух раз, вторая — комиссией", chunks[1].text)

    def test_every_fragment_has_the_document_prefix(self):
        chunks = chunk([heading("1.", "Общие положения"), clause("1.1.", "Текст пункта.")], "Положение о стипендиях")
        self.assertTrue(chunks[0].text.startswith("[Положение о стипендиях › Раздел 1 › п. 1.1]\n"))
        self.assertEqual(chunks[0].section_path, "Раздел 1 › п. 1.1")
        self.assertEqual(chunks[0].body, "1.1. Текст пункта.")

    def test_sub_clause_joins_its_parent_while_it_fits(self):
        chunks = chunk([heading("2.", "Сроки"), clause("2.3.", "Родитель."), clause("2.3.1.", "Подпункт."),
                        clause("2.4.", "Соседний пункт.")], "Док")
        self.assertEqual(len(chunks), 2)
        self.assertIn("2.3.1. Подпункт.", chunks[0].body)
        self.assertEqual(chunks[0].section_path, "Раздел 2 › п. 2.3")

    def test_table_is_a_separate_fragment_with_its_caption(self):
        head, rows = ["Вид", "Размер"], [["ГАС", "3600 руб."], ["ГАС на отлично", "5400 руб."]]
        blocks = [heading("2.", "Виды стипендий"), clause("2.1.", "Размеры в Таблице 1."),
                  Block("paragraph", "Таблица 1. Размеры стипендий", page=1),
                  Block("table", table_text(head, rows), page=1, head=head, rows=rows)]
        chunks = chunk(blocks, "Положение")
        table = [c for c in chunks if c.kind == "table"]
        self.assertEqual(len(table), 1)
        self.assertEqual(table[0].section_path, "Раздел 2 › Таблица 1")
        self.assertIn("Таблица 1. Размеры стипендий", table[0].text)
        self.assertIn("Вид: ГАС на отлично; Размер: 5400 руб.", table[0].text)

    def test_long_clause_is_cut_by_sentences_with_overlap(self):
        sentences = [f"Предложение номер {i} содержит канцелярский текст о сроках и порядке подачи заявлений студентами." for i in range(60)]
        chunks = chunk([heading("3.", "Длинный"), clause("3.1.", " ".join(sentences))], "Док")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(c.section_path == "Раздел 3 › п. 3.1" for c in chunks))
        self.assertTrue(all(count_tokens(c.body) <= LIMIT for c in chunks))
        last_of_first = chunks[0].body.split(". ")[-1].rstrip(".")
        self.assertIn(last_of_first, chunks[1].body)  # one sentence of overlap

    def test_huge_table_is_cut_by_rows_with_the_header_repeated(self):
        head = ["Документ", "Срок"]
        rows = [[f"Справка номер {i} для очень важного и длинного назначения", f"{i} рабочих дней"] for i in range(200)]
        chunks = chunk([heading("1.", "Сроки"), Block("table", table_text(head, rows), head=head, rows=rows)], "Док")
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all("Документ | Срок" in c.text for c in chunks))
        joined = "\n".join(c.text for c in chunks)
        self.assertIn("Справка номер 0 ", joined)
        self.assertIn("Справка номер 199 ", joined)

    def test_gold_section_matching(self):
        self.assertTrue(matches_section("Раздел 4 › п. 4.2", "4.2"))
        self.assertFalse(matches_section("Раздел 4 › п. 4.2.1", "4.2"))
        self.assertFalse(matches_section("Раздел 4 › п. 4.21", "4.2"))
        self.assertTrue(matches_section("Раздел 2 › Таблица 1", "table-1"))
        self.assertTrue(matches_section("Частые вопросы › 1. Какие справки?", "faq-1"))


@unittest.skipUnless(HAS_KB_EXTRAS, "pdfplumber/beautifulsoup4 not installed (pip install -e .[kb])")
class RealFilesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from hse_schedule.assistant.kb.ingest import parse_file

        manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))["documents"]
        cls.chunks = {d["doc_id"]: chunk(parse_file(DATA / d["source_path"]), d["title"]) for d in manifest}
        cls.manifest = manifest

    def test_every_pdf_gives_fragments_and_a_table(self):
        pdfs = [d["doc_id"] for d in self.manifest if d["source_path"].endswith(".pdf")]
        self.assertEqual(len(pdfs), 11)
        for doc_id in pdfs:
            with self.subTest(doc_id=doc_id):
                self.assertTrue(self.chunks[doc_id])
                self.assertTrue(any(c.kind == "table" for c in self.chunks[doc_id]))

    def test_cross_page_table_is_whole(self):
        tables = [c for c in self.chunks["10"] if c.kind == "table"]
        self.assertEqual(len(tables), 1)
        text = tables[0].text
        self.assertIn("Справка об обучении (электронная)", text)  # first row, page 1
        self.assertIn("Дубликат студенческого билета; Как заказать: заявление; Срок: 5 рабочих дней", text)  # page 2
        self.assertEqual(text.count("Документ | Как заказать | Срок"), 1)  # repeated page header not duplicated

    def test_service_text_is_dropped(self):
        for doc_id, chunks in self.chunks.items():
            joined = "\n".join(c.body for c in chunks)
            with self.subTest(doc_id=doc_id):
                self.assertNotIn("УТВЕРЖДАЮ", joined)
                self.assertNotIn("Страница ", joined)
                self.assertNotIn("Лист согласования", joined)
                self.assertNotIn("Главная Учёба", joined)  # portal menu

    def test_html_faq_and_important_blocks(self):
        dorm = self.chunks["web-dorm"]
        self.assertTrue(any(c.kind == "faq" and "086/у" in c.text for c in dorm))
        self.assertTrue(any("Важно: Заселение возможно только" in c.text for c in dorm))

    def test_gold_sections_exist_for_every_answerable_question(self):
        questions = json.loads((DATA / "questions.json").read_text(encoding="utf-8"))["questions"]
        for q in questions:
            if q["answerable"]:
                with self.subTest(q=q["id"]):
                    hits = [c for c in self.chunks[q["gold_doc_id"]] if matches_section(c.section_path, q["gold_section"])]
                    self.assertTrue(hits, "gold fragment not found")
                    self.assertTrue(all(any(m in c.text for c in hits) for m in q["must_contain"]))


if __name__ == "__main__":
    unittest.main()
