"""Attachment files: type by content, limits, safe names, metadata removal, text."""

from __future__ import annotations

import io
import os
import unittest
import zipfile
from unittest import mock

from hse_schedule.attachments.files import AttachmentError, extract_text, limits, prepare, safe_name, sniff
from tests import attachment_samples as samples


class TypeTests(unittest.TestCase):
    def test_type_comes_from_content_not_the_name(self):
        self.assertEqual(prepare(samples.png(), "photo.pdf").kind, "png")
        self.assertEqual(prepare(samples.png(), "photo.pdf").name, "photo.png")  # the real extension wins
        with self.assertRaises(AttachmentError) as error:
            prepare(samples.exe_named_pdf(), "statement.pdf")
        self.assertEqual(error.exception.code, "unsupported_type")
        self.assertIn("PDF, DOCX, JPEG или PNG", error.exception.message)

    def test_plain_zip_is_not_a_docx(self):
        out = io.BytesIO()
        with zipfile.ZipFile(out, "w") as z:
            z.writestr("readme.txt", "hello")
        with self.assertRaises(AttachmentError):
            sniff(out.getvalue())

    def test_size_limit_from_settings(self):
        with mock.patch.dict(os.environ, {"ATTACHMENT_MAX_MB": "1"}):
            self.assertEqual(limits().max_bytes, 1024 * 1024)
            with self.assertRaises(AttachmentError) as error:
                prepare(b"%PDF-1.4" + b"0" * (1024 * 1024), "big.pdf")
        self.assertEqual((error.exception.code, error.exception.status), ("too_large", 413))
        self.assertEqual(limits().max_files, 5)

    def test_broken_files_get_a_clear_error(self):
        with self.assertRaises(AttachmentError) as error:
            prepare(b"\x89PNG\r\n\x1a\nnot really a png", "x.png")
        self.assertEqual(error.exception.code, "bad_file")
        with self.assertRaises(AttachmentError):
            prepare(b"", "empty.pdf")


class NameTests(unittest.TestCase):
    def test_paths_and_special_characters_are_removed(self):
        self.assertEqual(safe_name("../../etc/passwd.pdf", "pdf"), "passwd.pdf")
        self.assertEqual(safe_name(r"C:\Users\x\справка №1.pdf", "pdf"), "справка №1.pdf")
        self.assertEqual(safe_name('a"b<c>|d\r\n.jpg', "jpeg"), "a_b_c__d.jpg")
        self.assertEqual(safe_name("", "png"), "файл.png")


class MetadataTests(unittest.TestCase):
    def test_exif_is_removed_from_photos(self):
        from PIL import Image

        raw = samples.jpeg_with_exif()
        self.assertTrue(Image.open(io.BytesIO(raw)).getexif())  # the sample really has EXIF
        clean = prepare(raw, "photo.jpg").data
        self.assertFalse(Image.open(io.BytesIO(clean)).getexif())

    def test_png_text_chunks_are_removed(self):
        from PIL import Image

        self.assertIn("Author", Image.open(io.BytesIO(samples.png())).info)
        self.assertNotIn("Author", Image.open(io.BytesIO(prepare(samples.png(), "a.png").data)).info)

    def test_pdf_author_is_removed(self):
        from pypdf import PdfReader

        raw = samples.pdf("Hello")
        self.assertEqual(PdfReader(io.BytesIO(raw)).metadata.author, "Иван Выдуманный")
        meta = PdfReader(io.BytesIO(prepare(raw, "a.pdf").data)).metadata
        self.assertTrue(meta is None or not meta.author)

    def test_docx_author_is_removed_and_text_kept(self):
        clean = prepare(samples.docx("Обычный текст заявления"), "a.docx").data
        with zipfile.ZipFile(io.BytesIO(clean)) as z:
            self.assertNotIn("Выдуманный", z.read("docProps/core.xml").decode())
        self.assertEqual(extract_text("docx", clean), "Обычный текст заявления")

    def test_pdf_text_is_extracted(self):
        self.assertIn("Hello test", extract_text("pdf", samples.pdf("Hello test")))
        self.assertIsNone(extract_text("png", samples.png()))


if __name__ == "__main__":
    unittest.main()
