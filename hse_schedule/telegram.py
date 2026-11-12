"""Telegram delivery and private, single-use account linking through /start."""

from __future__ import annotations

import logging
import re
import ssl
from datetime import datetime
from typing import TYPE_CHECKING

import httpx

from .push import ChannelDeliveryError

if TYPE_CHECKING:
    from .notification_store import NotificationStore


class _TokenLogFilter(logging.Filter):
    """httpx logs full request URLs at INFO; Telegram puts its token in them."""

    def __init__(self, token: str) -> None:
        super().__init__()
        self._token = token

    def filter(self, record: logging.LogRecord) -> bool:
        message = record.getMessage()
        if self._token in message:
            record.msg = message.replace(self._token, "[redacted]")
            record.args = ()
        return True


class TelegramBot:
    def __init__(
        self,
        token: str,
        *,
        username: str | None = None,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        if not isinstance(token, str) or not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]+", token):
            raise ValueError("Некорректный токен Telegram-бота.")
        if username is not None and not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            raise ValueError("Некорректное имя Telegram-бота.")
        self._token = token
        self._username = username
        self._transport = transport
        self._offset = 0
        logging.getLogger("httpx").addFilter(_TokenLogFilter(token))

    def _call(self, method: str, payload: dict) -> object:
        try:
            with httpx.Client(
                timeout=10,
                follow_redirects=False,
                verify=ssl.create_default_context(),
                transport=self._transport,
            ) as client:
                response = client.post(f"https://api.telegram.org/bot{self._token}/{method}", json=payload)
            result = response.json()
        except (httpx.HTTPError, ValueError):
            raise ChannelDeliveryError("Telegram временно недоступен.") from None
        if not isinstance(result, dict):
            raise ChannelDeliveryError("Telegram вернул некорректный ответ.")
        if response.status_code >= 300 or result.get("ok") is not True:
            code = result.get("error_code", response.status_code)
            description = result.get("description", "")
            invalid_chat = isinstance(description, str) and any(
                text in description.lower() for text in ("chat not found", "chat_id is empty", "user is deactivated")
            )
            raise ChannelDeliveryError(
                "Не удалось выполнить запрос к Telegram.",
                permanent=code in (400, 401, 403, 404, 410),
                remove_target=code == 403 or (code == 400 and invalid_chat),
            )
        return result.get("result")

    def get_username(self) -> str:
        if self._username is None:
            result = self._call("getMe", {})
            username = result.get("username") if isinstance(result, dict) else None
            if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
                raise ChannelDeliveryError("Telegram не вернул имя бота.")
            self._username = username
        return self._username

    def send(self, target: dict, notification: dict) -> None:
        chat_id = target.get("chat_id")
        if not isinstance(chat_id, str) or not chat_id.isascii() or not chat_id.isdecimal() or int(chat_id) <= 0:
            raise ChannelDeliveryError("Недействительная привязка Telegram.", permanent=True, remove_target=True)
        text = f"{notification['title']}\n\n{notification['body']}"[:4096]
        self._call(
            "sendMessage",
            {"chat_id": chat_id, "text": text, "link_preview_options": {"is_disabled": True}},
        )

    def poll_once(self, store: NotificationStore, now: datetime) -> None:
        """Consume private /start links; no username or arbitrary message can bind.

        The database validates expiry and consumes the nonce atomically. Polling
        replay after restart therefore cannot re-bind an already used link.
        """
        updates = self._call(
            "getUpdates", {"offset": self._offset, "timeout": 0, "allowed_updates": ["message"]}
        )
        if not isinstance(updates, list):
            raise ChannelDeliveryError("Telegram вернул некорректные обновления.")
        for update in updates:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                continue
            self._offset = max(self._offset, update["update_id"] + 1)
            message = update.get("message")
            if not isinstance(message, dict):
                continue
            chat, sender, text = message.get("chat"), message.get("from"), message.get("text")
            if not isinstance(chat, dict) or not isinstance(sender, dict) or not isinstance(text, str):
                continue
            chat_id = chat.get("id")
            if (
                chat.get("type") != "private"
                or type(chat_id) is not int
                or chat_id <= 0
                or sender.get("id") != chat_id
                or sender.get("is_bot") is True
            ):
                continue
            command = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)? ([A-Za-z0-9_-]{16,64})", text.strip())
            if not command:
                continue
            username = sender.get("username")
            if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
                username = None
            email = store.consume_telegram_link(command.group(1), str(chat_id), username, now)
            if email is not None:
                try:
                    self.send(
                        {"chat_id": str(chat_id)},
                        {"title": "Telegram привязан", "body": "Настройки уведомлений доступны в личном кабинете."},
                    )
                except ChannelDeliveryError:
                    # The binding is already committed; a failed confirmation
                    # must not replay its consumed linking token.
                    pass
