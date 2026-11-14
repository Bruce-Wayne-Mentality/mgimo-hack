import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from hse_schedule.cli import main


ROOT = Path(__file__).resolve().parents[1]


class CLITests(unittest.TestCase):
    def test_saved_source_can_be_parsed_without_network(self):
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "parsed.json"
            result = main(["parse", "--input", str(ROOT / "examples/lessons.json"), "--output", str(output)])
            self.assertEqual(result, 0)
            self.assertEqual(len(json.loads(output.read_text())), 6)

    def test_personal_lookup_normalizes_email_and_outputs_json(self):
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            result = main([
                "schedule", "--students", str(ROOT / "examples/students.json"),
                "--fixture", str(ROOT / "examples/lessons.json"),
                "--email", " ANNA@demo-university.test ",
                "--start", "2026-11-09", "--finish", "2026-11-15",
            ])
        self.assertEqual(result, 0)
        self.assertEqual(len(json.loads(stdout.getvalue())), 4)

    def test_failure_writes_error_and_never_successful_empty_json(self):
        stderr, stdout = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            result = main(["parse", "--input", "nonexistent-file.json"])
        self.assertEqual(result, 1)
        self.assertEqual(stdout.getvalue(), "")
        self.assertIn("Ошибка:", stderr.getvalue())

    def test_real_server_requires_explicit_tokens(self):
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            result = main(["serve"])
        self.assertEqual(result, 1)
        self.assertIn("tokens-file", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
