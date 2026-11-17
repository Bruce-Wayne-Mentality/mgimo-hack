"""Gaps queue: refusal → staff answer → the same question is answered from faq-staff."""

from __future__ import annotations

import importlib.util
import os
import unittest
from unittest import mock

from fastapi.testclient import TestClient

from tests.test_assistant_rag import StubGiga
from tests.test_features import ANNA, BORIS, STAFF, FeatureTestCase

HAS_KB_EXTRAS = importlib.util.find_spec("pdfplumber") is not None and importlib.util.find_spec("bs4") is not None
QUESTION = "Можно ли оставить велосипед на ночь во дворе корпуса?"


@unittest.skipUnless(HAS_KB_EXTRAS, "pdfplumber/beautifulsoup4 not installed (pip install -e .[kb])")
class KbGapsTests(FeatureTestCase):
    @classmethod
    def setUpClass(cls):
        cls._env = mock.patch.dict(os.environ, {"RAG_ENABLED": "true"})
        cls._env.start()
        cls._giga = mock.patch("hse_schedule.assistant.router.GigaChat.from_env", return_value=StubGiga())
        cls._giga.start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._giga.stop()
        cls._env.stop()

    def ask(self, text: str, account=ANNA) -> dict:
        response = self.client(account).post("/api/assistant/ask", json={"message": text})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def gaps(self, status: str = "open") -> list[dict]:
        response = self.client(STAFF).get(f"/api/staff/kb/gaps?status={status}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["items"]

    def test_students_get_403_and_anonymous_401(self):
        self.assertEqual(self.client(ANNA).get("/api/staff/kb/gaps").status_code, 403)
        anonymous = TestClient(self.app, base_url="https://testserver")
        self.assertEqual(anonymous.get("/api/staff/kb/gaps").status_code, 401)
        fake = "00000000-0000-0000-0000-000000000000"
        self.assertEqual(self.client(BORIS).post(f"/api/staff/kb/gaps/{fake}/reject").status_code, 403)

    def test_refusal_staff_answer_and_the_same_question_answered(self):
        first = self.ask(QUESTION)
        self.assertEqual(first["kind"], "kb_refusal")
        gap = next(g for g in self.gaps() if g["question"] == QUESTION)
        response = self.client(STAFF).post(f"/api/staff/kb/gaps/{gap['id']}/answer", json={
            "answer_text": "Нет, велосипеды оставляют только на велопарковке у корпуса А до 22:00.", "publish": True})
        self.assertEqual(response.status_code, 200, response.text)
        self.assertTrue(response.json()["published"])
        again = self.ask(QUESTION, BORIS)
        self.assertNotEqual(again["kind"], "kb_refusal")
        self.assertEqual(again["sources"][0]["doc_id"], "faq-staff")
        self.assertIn("велопарковке у корпуса А до 22:00", again["text"])
        self.assertNotIn(gap["id"], [g["id"] for g in self.gaps()])
        self.assertEqual(self.client(STAFF).post(f"/api/staff/kb/gaps/{gap['id']}/reject").status_code, 409)

    def test_queue_has_no_student_identity_or_contacts(self):
        self.ask("Сколько стоит абонемент в бассейн? Пишите anna.private@example.org или +7 916 777-88-99")
        items = self.gaps()
        self.assertTrue(any("абонемент в бассейн" in g["question"] for g in items))  # really queued, not vacuous
        dump = str(items)
        self.assertNotIn("anna.private@example.org", dump)
        self.assertNotIn("777-88-99", dump)
        self.assertNotIn("student.anna", dump)
        self.assertTrue(all(set(g) == {"id", "question", "status", "top_score", "nearest", "answer_text", "answered_by",
                                       "created_at", "answered_at"} for g in items))

    def test_reject_and_csrf(self):
        self.ask("Когда в столовой будет пицца?")
        gap = next(g for g in self.gaps() if "пицца" in g["question"])
        no_csrf = TestClient(self.app, base_url="https://testserver")
        no_csrf.cookies = self.client(STAFF).cookies
        self.assertEqual(no_csrf.post(f"/api/staff/kb/gaps/{gap['id']}/reject").status_code, 403)
        self.assertEqual(self.client(STAFF).post(f"/api/staff/kb/gaps/{gap['id']}/reject").status_code, 200)
        self.assertIn(gap["id"], [g["id"] for g in self.gaps("rejected")])


if __name__ == "__main__":
    unittest.main()
