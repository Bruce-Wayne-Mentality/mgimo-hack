"""K4 knowledge base: university rules as documents, fragments and vectors (RAG).

Importing the package registers its tables in Base.metadata.
"""

import os
from pathlib import Path

from . import models  # noqa: F401  (registers tables)

STAFF_DOC = "faq-staff"  # answers published by deanery staff from the gaps queue
DEFAULT_MANIFEST = Path(__file__).resolve().parents[3] / "rag_test_data" / "manifest.json"


def rag_enabled() -> bool:
    """RAG_ENABLED=true switches the assistant to the knowledge base; off by default."""
    return os.environ.get("RAG_ENABLED", "").strip().lower() in ("1", "true", "yes", "on")


def manifest_path() -> Path:
    return Path(os.environ.get("KB_MANIFEST") or DEFAULT_MANIFEST)
