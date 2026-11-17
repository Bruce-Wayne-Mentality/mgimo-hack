"""Keys for the red button (spec, section 6).

- Buffer: AES-256-GCM with a key of the day. Day keys live outside the
  database (a key directory not included in DB backups); the purger deletes
  the key of day D on D+15, after which any leftover copies are unreadable.
- Registry: envelope encryption — every complaint has its own DEK, wrapped by
  a master key. Deleting the DEK deletes the text.
- Peppers: HMAC keys for author_ref (anonymity before reviewers) and for
  text_hmac in moderation events (duplicate detection without the text).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import threading
from datetime import date, timedelta
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

DEFAULT_KEY_DIR = Path(".local-state/keys")


class KeyStore:
    def __init__(self, key_dir: str | Path | None = None) -> None:
        self.dir = Path(key_dir or os.environ.get("REDBUTTON_KEY_DIR") or DEFAULT_KEY_DIR)
        self._lock = threading.Lock()
        self._cache: dict[str, bytes] = {}

    # ---- key files ---------------------------------------------------------

    def _key(self, name: str, *, create: bool = True) -> bytes | None:
        with self._lock:
            if name in self._cache:
                return self._cache[name]
            path = self.dir / name
            if not path.exists():
                if not create:
                    return None
                self.dir.mkdir(parents=True, exist_ok=True)
                try:
                    self.dir.chmod(0o700)
                except OSError:
                    pass
                tmp = path.with_suffix(".tmp")
                tmp.write_bytes(secrets.token_bytes(32))
                try:
                    tmp.chmod(0o600)
                except OSError:
                    pass
                tmp.replace(path)
            value = path.read_bytes()
            if len(value) != 32:
                raise ValueError(f"Повреждён ключ {name}")
            self._cache[name] = value
            return value

    @staticmethod
    def day_id(day: date) -> str:
        return day.strftime("%Y%m%d")

    def purge_day_keys(self, today: date, keep_days: int = 15) -> int:
        """Crypto-shredding: buffer copies encrypted with old day keys become unreadable."""
        removed = 0
        if not self.dir.exists():
            return 0
        border = self.day_id(today - timedelta(days=keep_days))
        for path in self.dir.glob("day-*.key"):
            if path.stem.removeprefix("day-") < border:
                path.unlink(missing_ok=True)
                with self._lock:
                    self._cache.pop(path.name, None)
                removed += 1
        return removed

    # ---- buffer (key of the day) --------------------------------------------

    def seal_buffer(self, text: str, day: date, aad: str) -> tuple[str, bytes, bytes]:
        key_id = self.day_id(day)
        nonce = secrets.token_bytes(12)
        ct = AESGCM(self._key(f"day-{key_id}.key")).encrypt(nonce, text.encode("utf-8"), aad.encode("utf-8"))
        return key_id, nonce, ct

    def open_buffer(self, key_id: str, nonce: bytes, ct: bytes, aad: str) -> str | None:
        key = self._key(f"day-{key_id}.key", create=False)
        if key is None:
            return None  # shredded
        return AESGCM(key).decrypt(nonce, ct, aad.encode("utf-8")).decode("utf-8")

    # ---- registry (envelope) ------------------------------------------------

    def new_dek(self) -> tuple[bytes, bytes]:
        """Returns (dek, wrapped_dek)."""
        dek = AESGCM.generate_key(bit_length=256)
        nonce = secrets.token_bytes(12)
        wrapped = nonce + AESGCM(self._key("master.key")).encrypt(nonce, dek, b"complaint-dek")
        return dek, wrapped

    def unwrap(self, wrapped: bytes) -> bytes:
        return AESGCM(self._key("master.key")).decrypt(wrapped[:12], wrapped[12:], b"complaint-dek")

    @staticmethod
    def seal(dek: bytes, text: str, aad: str) -> bytes:
        nonce = secrets.token_bytes(12)
        return nonce + AESGCM(dek).encrypt(nonce, text.encode("utf-8"), aad.encode("utf-8"))

    @staticmethod
    def open(dek: bytes, blob: bytes, aad: str) -> str:
        return AESGCM(dek).decrypt(blob[:12], blob[12:], aad.encode("utf-8")).decode("utf-8")

    # ---- peppers -------------------------------------------------------------

    def author_ref(self, user_id) -> str:
        """HMAC(pepper_anon, user_id): the student finds own complaints, reviewers cannot."""
        return hmac.new(self._key("pepper-anon.key"), str(user_id).encode(), hashlib.sha256).hexdigest()

    def text_hmac(self, normalized: str) -> str:
        return hmac.new(self._key("pepper-text.key"), normalized.encode("utf-8"), hashlib.sha256).hexdigest()

    def pseudonym(self, complaint_id) -> str:
        digest = hmac.new(self._key("pepper-anon.key"), f"alias|{complaint_id}".encode(), hashlib.sha256).hexdigest()
        return f"Студент #{digest[:4].upper()}"

    def day_salt_ref(self, user_id, day: date) -> str:
        """Daily-rotating reference for the in-memory submission limit."""
        salt = hashlib.sha256(self._key("pepper-anon.key") + self.day_id(day).encode()).digest()
        return base64.urlsafe_b64encode(hmac.new(salt, str(user_id).encode(), hashlib.sha256).digest()[:12]).decode()
