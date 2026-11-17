"""Retrieval evaluation entry point — same as `python -m hse_schedule.cli kb-eval`.

    python tools/rag_eval/eval_retrieval.py --questions rag_test_data/questions.json [--bm25-only] [--calibrate]

The logic lives in hse_schedule/assistant/kb/evaluation.py so that the CLI and
the regression test (tests/test_kb_eval.py) use exactly the same code.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from hse_schedule.cli import main  # noqa: E402

if __name__ == "__main__":
    raise SystemExit(main(["kb-eval", *sys.argv[1:]]))
