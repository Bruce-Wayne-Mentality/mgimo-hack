"""Files on disk: random uuid names in ATTACHMENTS_DIR, never under the public static root."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

from .files import storage_dir


def _path(key: str) -> Path:
    uuid.UUID(key)  # only our own uuid names: no path tricks
    return storage_dir() / key


def write(data: bytes) -> str:
    key = str(uuid.uuid4())
    path = _path(key)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)
    return key


def read(key: str) -> bytes | None:
    path = _path(key)
    return path.read_bytes() if path.is_file() else None


def delete(key: str) -> None:
    _path(key).unlink(missing_ok=True)
