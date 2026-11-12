"""Validated browser subscriptions and persistent VAPID Web Push delivery."""

from __future__ import annotations

import base64
import binascii
import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from .errors import ConfigurationError


class ChannelDeliveryError(Exception):
    """A sanitized delivery failure, safe for worker logs and API responses."""

    def __init__(
        self,
        message: str = "Канал уведомлений временно недоступен.",
        *,
        permanent: bool = False,
        remove_target: bool = False,
    ) -> None:
        super().__init__(message)
        self.permanent = permanent
        self.remove_target = remove_target


def _decode_key(value: object, *, length: int) -> bytes:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]+={0,2}", value):
        raise ValueError("Некорректный ключ push-подписки.")
    try:
        decoded = base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except (ValueError, binascii.Error):
        raise ValueError("Некорректный ключ push-подписки.") from None
    if len(decoded) != length:
        raise ValueError("Некорректная длина ключа push-подписки.")
    return decoded


def validate_subscription(subscription: object) -> dict:
    """Accept only HTTPS push-service URLs and valid Web Push encryption keys.

    Endpoint URLs are supplied by the browser; they must never turn the backend
    into an HTTP client for arbitrary URLs supplied by an account.
    """
    if not isinstance(subscription, dict):
        raise ValueError("Ожидалась push-подписка браузера.")
    endpoint = subscription.get("endpoint")
    if not isinstance(endpoint, str) or len(endpoint) > 2048 or any(c.isspace() for c in endpoint):
        raise ValueError("Некорректный адрес push-подписки.")
    try:
        url = urlsplit(endpoint)
        host = (url.hostname or "").lower()
        allowed = (
            host == "fcm.googleapis.com"
            or host == "web.push.apple.com"
            or host.endswith(".push.services.mozilla.com")
            or host.endswith(".notify.windows.com")
        )
        if (
            url.scheme != "https"
            or not allowed
            or url.username is not None
            or url.password is not None
            or url.port not in (None, 443)
            or url.fragment
            or not url.path
        ):
            raise ValueError("Неподдерживаемый адрес push-сервиса браузера.")
    except ValueError:
        raise ValueError("Неподдерживаемый адрес push-сервиса браузера.") from None
    keys = subscription.get("keys")
    if not isinstance(keys, dict):
        raise ValueError("В push-подписке отсутствуют ключи шифрования.")
    public_key = _decode_key(keys.get("p256dh"), length=65)
    _decode_key(keys.get("auth"), length=16)
    try:
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), public_key)
    except ValueError:
        raise ValueError("Некорректный публичный ключ push-подписки.") from None
    return {
        "endpoint": endpoint,
        "keys": {"p256dh": keys["p256dh"], "auth": keys["auth"]},
    }


def _validate_contact(contact: str) -> None:
    if not isinstance(contact, str) or any(c.isspace() for c in contact):
        raise ConfigurationError("Укажите VAPID-контакт в формате mailto:email или HTTPS URL.")
    url = urlsplit(contact)
    if url.scheme == "mailto" and re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", url.path):
        if not url.query and not url.fragment:
            return
    if url.scheme == "https" and url.hostname and not url.username and not url.password:
        return
    raise ConfigurationError("Укажите VAPID-контакт в формате mailto:email или HTTPS URL.")


class WebPushSender:
    def __init__(
        self,
        private_key_path: Path | str,
        contact: str = "mailto:notifications@university.test",
    ) -> None:
        _validate_contact(contact)
        self.private_key_path = Path(private_key_path)
        self.contact = contact
        try:
            self.private_key_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            if not self.private_key_path.exists():
                self._create_key()
            os.chmod(self.private_key_path, 0o600)
            key = serialization.load_pem_private_key(self.private_key_path.read_bytes(), password=None)
            if not isinstance(key, ec.EllipticCurvePrivateKey) or not isinstance(key.curve, ec.SECP256R1):
                raise ValueError("Not a VAPID P-256 key")
            public_bytes = key.public_key().public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
            self.public_key = base64.urlsafe_b64encode(public_bytes).decode().rstrip("=")
        except (OSError, ValueError, TypeError):
            raise ConfigurationError("Не удалось создать или прочитать ключ браузерных уведомлений.") from None

    def _create_key(self) -> None:
        private_key = ec.generate_private_key(ec.SECP256R1()).private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
        # Link a completely written file into place without replacing a key
        # another process may have created in the meantime.
        temporary: str | None = None
        try:
            with tempfile.NamedTemporaryFile(dir=self.private_key_path.parent, prefix=".vapid-", delete=False) as stream:
                temporary = stream.name
                stream.write(private_key)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                os.link(temporary, self.private_key_path)
            except FileExistsError:
                pass
        finally:
            if temporary is not None:
                Path(temporary).unlink(missing_ok=True)

    def send(self, target: dict, notification: dict) -> None:
        try:
            subscription = validate_subscription(target)
        except ValueError:
            raise ChannelDeliveryError("Push-подписка недействительна.", permanent=True, remove_target=True) from None
        ttl = 300
        details = notification.get("payload")
        lesson = details.get("lesson") if isinstance(details, dict) else None
        if notification.get("kind") == "reminder" and isinstance(lesson, dict) and "starts_at" in lesson:
            try:
                starts = datetime.fromisoformat(lesson["starts_at"])
                if starts.tzinfo is None or starts.utcoffset() is None:
                    raise ValueError("Missing timezone")
                remaining = (starts - datetime.now(timezone.utc)).total_seconds()
            except (ValueError, TypeError):
                raise ChannelDeliveryError("Некорректное время напоминания.", permanent=True) from None
            if remaining <= 0:
                raise ChannelDeliveryError("Время напоминания истекло.", permanent=True)
            # Providers may retain a notification until the device reconnects.
            # Never retain a reminder beyond the start of its lesson; TTL=0
            # requests immediate delivery only for a subsecond remainder.
            ttl = min(ttl, int(remaining))
        payload = {
            "id": notification["id"],
            "title": notification["title"],
            "body": notification["body"],
            "url": "/",
            "tag": f"notification-{notification['id']}",
        }
        try:
            from pywebpush import WebPushException, webpush
        except ImportError:
            raise ChannelDeliveryError("Браузерные уведомления не настроены.", permanent=True) from None
        try:
            webpush(
                subscription_info=subscription,
                data=json.dumps(payload, ensure_ascii=False),
                vapid_private_key=str(self.private_key_path),
                vapid_claims={"sub": self.contact},
                ttl=ttl,
                timeout=10,
            )
        except WebPushException as error:
            status = getattr(error, "status_code", None)
            if status is None:
                response = getattr(error, "response", None)
                status = response.status_code if response is not None else None
            raise ChannelDeliveryError(
                "Не удалось доставить браузерное уведомление.",
                permanent=status in (400, 401, 403, 404, 410),
                remove_target=status in (404, 410),
            ) from None
        except Exception:
            # Underlying HTTP exceptions can include endpoint credentials.
            raise ChannelDeliveryError("Не удалось доставить браузерное уведомление.") from None
