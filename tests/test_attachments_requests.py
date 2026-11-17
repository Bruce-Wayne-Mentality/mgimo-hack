"""Attachments in request chats through the real API."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock
from urllib.parse import quote

from fastapi.testclient import TestClient

from tests import attachment_samples as samples
from tests.test_features import ADMIN, ANNA, BORIS, STAFF, FeatureTestCase


class RequestAttachmentTests(FeatureTestCase):
    @classmethod
    def setUpClass(cls):
        cls._files = tempfile.mkdtemp()
        cls._env = mock.patch.dict(os.environ, {"ATTACHMENTS_DIR": cls._files})
        cls._env.start()
        super().setUpClass()

    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        cls._env.stop()

    def open_request(self) -> str:
        items = self.client(ANNA).get("/api/requests").json()["items"]
        mine = next(r for r in items if r["status"] in ("submitted", "in_review", "needs_info"))
        return mine["id"]

    def upload(self, client, request_id: str, data: bytes, name: str):
        return client.post(f"/api/requests/{request_id}/attachments", content=data,
                           headers={"X-File-Name": quote(name), "Content-Type": "application/octet-stream"})

    def test_upload_send_and_download(self):
        rid = self.open_request()
        anna = self.client(ANNA)
        sent = self.upload(anna, rid, samples.jpeg_with_exif(), "../../фото справки.jpg")
        self.assertEqual(sent.status_code, 201, sent.text)
        file = sent.json()
        self.assertEqual((file["name"], file["kind"]), ("фото справки.jpg", "jpeg"))
        reply = anna.post(f"/api/requests/{rid}/comments", json={"body": "", "attachment_ids": [file["id"]]})
        self.assertEqual(reply.status_code, 200, reply.text)
        last = reply.json()["comments"][-1]
        self.assertEqual([a["id"] for a in last["attachments"]], [file["id"]])
        got = anna.get(file["url"])
        self.assertEqual(got.status_code, 200)
        self.assertTrue(got.headers["content-disposition"].startswith("attachment;"))
        self.assertEqual(got.headers["x-content-type-options"], "nosniff")
        self.assertEqual(got.headers["content-type"], "image/jpeg")
        self.assertNotIn(b"FakeCam", got.content)  # EXIF removed before storage
        self.assertEqual(self.client(ADMIN).get(file["url"]).status_code, 200)

    def test_another_student_gets_404(self):
        rid = self.open_request()
        file = self.upload(self.client(ANNA), rid, samples.pdf("Hello"), "a.pdf").json()
        self.client(ANNA).post(f"/api/requests/{rid}/comments", json={"body": "см. файл", "attachment_ids": [file["id"]]})
        boris = self.client(BORIS)
        self.assertEqual(boris.get(file["url"]).status_code, 404)
        self.assertEqual(self.upload(boris, rid, samples.png(), "x.png").status_code, 404)
        anonymous = TestClient(self.app, base_url="https://testserver")
        self.assertEqual(anonymous.get(file["url"]).status_code, 401)

    def test_unsent_file_is_only_for_its_uploader(self):
        rid = self.open_request()
        file = self.upload(self.client(ANNA), rid, samples.png(), "draft.png").json()
        self.assertEqual(self.client(ADMIN).get(file["url"]).status_code, 404)
        # someone else's staged file cannot be sent either
        reply = self.client(ADMIN).post(f"/api/requests/{rid}/comments", json={"body": "x", "attachment_ids": [file["id"]]})
        self.assertEqual(reply.status_code, 422)
        self.assertEqual(self.client(ANNA).delete(file["url"]).status_code, 204)
        self.assertEqual(self.client(ANNA).get(file["url"]).status_code, 404)

    def test_disguised_type_and_size_are_refused(self):
        rid = self.open_request()
        anna = self.client(ANNA)
        disguised = self.upload(anna, rid, samples.exe_named_pdf(), "заявление.pdf")
        self.assertEqual(disguised.status_code, 422)
        self.assertEqual(disguised.json()["error"]["code"], "unsupported_type")
        with mock.patch.dict(os.environ, {"ATTACHMENT_MAX_MB": "1"}):
            big = self.upload(anna, rid, b"%PDF-1.4" + b"0" * (1024 * 1024 + 10), "big.pdf")
        self.assertEqual(big.status_code, 413)
        self.assertIn("1 МБ", big.json()["error"]["message"])

    def test_too_many_files_in_one_message(self):
        rid = self.open_request()
        anna = self.client(ANNA)
        ids = [self.upload(anna, rid, samples.png(str(i)), f"{i}.png").json()["id"] for i in range(6)]
        reply = anna.post(f"/api/requests/{rid}/comments", json={"body": "много", "attachment_ids": ids})
        self.assertEqual(reply.status_code, 422)
        for i in ids:
            anna.delete(f"/api/requests/{rid}/attachments/{i}")

    def test_internal_note_files_are_staff_only(self):
        rid = self.open_request()
        staff = self.client(ADMIN)
        file = self.upload(staff, rid, samples.docx(), "служебка.docx").json()
        note = staff.post(f"/api/requests/{rid}/comments", json={"body": "внутреннее", "internal": True, "attachment_ids": [file["id"]]})
        self.assertEqual(note.status_code, 200, note.text)
        self.assertEqual(self.client(ANNA).get(file["url"]).status_code, 404)
        self.assertEqual(staff.get(file["url"]).status_code, 200)

    def test_files_live_outside_static_under_uuid_names(self):
        rid = self.open_request()
        self.upload(self.client(ANNA), rid, samples.png(), "секрет.png")
        names = [p.name for p in Path(self._files).iterdir()]
        self.assertTrue(names)
        self.assertFalse(any("секрет" in n or n.endswith(".png") for n in names))

    def test_csrf_is_required(self):
        rid = self.open_request()
        anna = self.client(ANNA)
        no_csrf = TestClient(self.app, base_url="https://testserver")
        no_csrf.cookies = anna.cookies
        response = no_csrf.post(f"/api/requests/{rid}/attachments", content=samples.png(), headers={"X-File-Name": "a.png"})
        self.assertEqual(response.status_code, 403)


if __name__ == "__main__":
    unittest.main()
