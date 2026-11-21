"""Telegram delivery and private, single-use account linking through /start."""

from __future__ import annotations

import logging
import re
import ssl
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from . import telegram_commands as commands
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
        self._menu_set = False
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


    # ---- the panel: one message per chat, rewritten in place -----------------------------

    def reply(self, chat_id: int | str, text: str, *, markup: dict | None = None) -> int | None:
        payload = {"chat_id": str(chat_id), "text": text[:4096], "link_preview_options": {"is_disabled": True}}
        if markup is not None:
            payload["reply_markup"] = markup
        result = self._call("sendMessage", payload)
        return result.get("message_id") if isinstance(result, dict) else None

    def _delete(self, chat_id: int | str, message_id: int | None) -> None:
        if message_id is None:
            return
        try:
            self._call("deleteMessage", {"chat_id": str(chat_id), "message_id": int(message_id)})
        except ChannelDeliveryError:
            pass  # already gone or older than 48 hours: nothing to clean

    def _drop_reply_keyboard(self, chat_id: int | str) -> None:
        """The earlier version had a reply keyboard under the input; tabs now live under the panel."""
        try:
            message_id = self.reply(chat_id, "…", markup={"remove_keyboard": True})
            self._delete(chat_id, message_id)
        except ChannelDeliveryError:
            pass

    def _new_panel(self, store: NotificationStore, chat_id: int | str, text: str, markup: dict) -> None:
        """Replace the chat's panel: the previous one is deleted so the chat does not fill up."""
        self._delete(chat_id, store.telegram_panel(str(chat_id)))
        message_id = self.reply(chat_id, text, markup=markup)
        store.set_telegram_panel(str(chat_id), message_id)

    def _edit_panel(self, store: NotificationStore, chat_id: int | str, message_id: int, text: str, markup: dict) -> None:
        try:
            self._call("editMessageText", {"chat_id": str(chat_id), "message_id": int(message_id), "text": text[:4096],
                                           "reply_markup": markup, "link_preview_options": {"is_disabled": True}})
        except ChannelDeliveryError as error:
            if not error.permanent:
                raise
            # «message is not modified» (the same tab pressed twice) or the message is gone: a fresh panel
            # only in the second case — re-sending on every repeated press would spam the chat.
            if store.telegram_panel(str(chat_id)) != message_id:
                self._new_panel(store, chat_id, text, markup)
            return
        store.set_telegram_panel(str(chat_id), message_id)

    def set_menu(self) -> None:
        """The command list in Telegram's menu; set once per process, failures are retried later."""
        if self._menu_set:
            return
        self._call("setMyCommands", {"commands": commands.COMMANDS, "language_code": "ru"})
        self._call("setMyCommands", {"commands": commands.COMMANDS})
        self._call("setMyDescription", {"description": (
            "Бот «Цифрового деканата» (учебный концепт): расписание, уведомления об изменениях и напоминание перед парой. "
            "Привяжите аккаунт в личном кабинете → «Уведомления».")})
        self._call("setMyShortDescription", {"short_description": "Расписание и уведомления «Цифрового деканата» (концепт)."})
        self._menu_set = True

    def _view(self, store: NotificationStore, email: str, tab: str, now: datetime, schedule) -> tuple[str, dict]:
        lessons = None
        if schedule is not None:
            today = now.astimezone(commands.MOSCOW).date()
            try:
                lessons = schedule.get_schedule(email, today, today + timedelta(days=6))
            except Exception:
                lessons = None
        name, group = email, None
        directory = getattr(schedule, "directory", None)
        if directory is not None:
            try:
                student = directory.get(email)
                name = student.name
                oids = set(student.group_oids)
                group = next((g.name for lesson in lessons or () for g in getattr(lesson, "groups", ()) if g.oid in oids), None)
            except Exception:
                pass
        if lessons is None and tab in ("today", "tomorrow", "week"):
            return "Не удалось получить расписание. Попробуйте чуть позже.", commands.keyboard(tab)
        return commands.render(tab, profile=commands.Profile(name=name, group=group), lessons=lessons or (),
                               feed=store.list_notifications(email, limit=5), timer=store.telegram_timer(email), now=now)

    # ---- updates -------------------------------------------------------------------------

    def poll_once(self, store: NotificationStore, now: datetime, schedule=None) -> None:
        """Private chats only. /start <one-time token> binds a chat; the database consumes the
        token atomically, so a replay after restart cannot re-bind. Everything else is answered
        only for a chat that is already bound, with the account taken from that binding."""
        updates = self._call(
            "getUpdates", {"offset": self._offset, "timeout": 0, "allowed_updates": ["message", "callback_query"]}
        )
        if not isinstance(updates, list):
            raise ChannelDeliveryError("Telegram вернул некорректные обновления.")
        for update in updates:
            if not isinstance(update, dict) or type(update.get("update_id")) is not int:
                continue
            self._offset = max(self._offset, update["update_id"] + 1)
            try:
                if isinstance(update.get("callback_query"), dict):
                    self._on_press(store, update["callback_query"], now, schedule)
                elif isinstance(update.get("message"), dict):
                    self._on_message(store, update["message"], now, schedule)
            except ChannelDeliveryError:
                continue  # a reply that did not go through is not retried: the user can press again

    @staticmethod
    def _private(chat, sender) -> int | None:
        if not isinstance(chat, dict) or not isinstance(sender, dict):
            return None
        chat_id = chat.get("id")
        if chat.get("type") != "private" or type(chat_id) is not int or chat_id <= 0 \
                or sender.get("id") != chat_id or sender.get("is_bot") is True:
            return None
        return chat_id

    def _on_message(self, store: NotificationStore, message: dict, now: datetime, schedule) -> None:
        text = message.get("text")
        chat_id = self._private(message.get("chat"), message.get("from"))
        if chat_id is None or not isinstance(text, str):
            return
        link = re.fullmatch(r"/start(?:@[A-Za-z0-9_]+)? ([A-Za-z0-9_-]{16,64})", text.strip())
        if link:
            username = message["from"].get("username")
            if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
                username = None
            email = store.consume_telegram_link(link.group(1), str(chat_id), username, now)
            if email is None:
                self.reply(chat_id, commands.EXPIRED)
                return
            # The binding is already committed; a failed reply below must not replay the consumed token.
            self.reply(chat_id, "Telegram привязан ✅")
            self._drop_reply_keyboard(chat_id)
            text_, markup = self._view(store, email, "home", now, schedule)
            self._new_panel(store, chat_id, text_, markup)
            return
        email = store.telegram_email(str(chat_id))
        if not isinstance(email, str):
            self.reply(chat_id, commands.NOT_LINKED)
            return
        self._delete(chat_id, message.get("message_id"))  # typed commands do not stay in the chat
        tab = commands.tab_of(text)
        if tab == "unlink":
            self._delete(chat_id, store.telegram_panel(str(chat_id)))
            store.set_telegram_panel(str(chat_id), None)
            store.unlink_telegram_target(email, str(chat_id))
            self.reply(chat_id, commands.UNLINKED, markup={"remove_keyboard": True})
            return
        if tab is None:
            minutes = commands.timer_value(text)
            if minutes is not None:
                store.set_telegram_timer(email, minutes)
                tab = "timer"
        if text.strip().split()[0].split("@")[0].lower() == "/start":
            self._drop_reply_keyboard(chat_id)
        text_, markup = self._view(store, email, tab or "home", now, schedule)
        self._new_panel(store, chat_id, text_, markup)

    def _on_press(self, store: NotificationStore, press: dict, now: datetime, schedule) -> None:
        message = press.get("message") if isinstance(press.get("message"), dict) else {}
        chat_id = self._private(message.get("chat"), press.get("from"))
        data = press.get("data") if isinstance(press.get("data"), str) else ""
        notice = None
        try:
            email = store.telegram_email(str(chat_id)) if chat_id is not None else None
            if not isinstance(email, str):
                notice = "Чат не привязан к кабинету"
                return
            tab = None
            if data.startswith("tab:"):
                tab = data[4:]
            elif data.startswith("timer:") and data[6:].isdecimal():
                minutes = int(data[6:])
                if minutes == 0 or minutes in commands.TIMER_CHOICES:
                    store.set_telegram_timer(email, minutes or None)
                    notice = f"Напоминание за {minutes} мин" if minutes else "Напоминание выключено"
                    tab = "timer"
            if tab not in ("home", "today", "tomorrow", "week", "notifications", "timer"):
                return
            text_, markup = self._view(store, email, tab, now, schedule)
            self._edit_panel(store, chat_id, message.get("message_id"), text_, markup)
        finally:
            if isinstance(press.get("id"), str):
                payload = {"callback_query_id": press["id"]}
                if notice:
                    payload["text"] = notice
                try:
                    self._call("answerCallbackQuery", payload)
                except ChannelDeliveryError:
                    pass

    # ---- lesson timer --------------------------------------------------------------------

    def send_reminders(self, store: NotificationStore, now: datetime, schedule) -> int:
        """«Через N мин — пара»: only for chats that switched the timer on (off by default), once per lesson."""
        if schedule is None:
            return 0
        sent = 0
        today = now.astimezone(commands.MOSCOW).date()
        for email, chat_id, minutes in store.telegram_timers():
            try:
                lessons = schedule.get_schedule(email, today, today + timedelta(days=1))
            except Exception:
                continue
            for lesson in lessons:
                if lesson.change is not None and lesson.change.kind == "cancelled":
                    continue
                if not (lesson.starts_at - timedelta(minutes=minutes) <= now < lesson.starts_at):
                    continue
                key = f"{lesson.id}|{lesson.starts_at.isoformat()}"
                if not store.claim_telegram_reminder(chat_id, key, minutes, now):
                    continue
                try:
                    self.reply(chat_id, commands.reminder_text(lesson, minutes))
                    sent += 1
                except ChannelDeliveryError:
                    pass
        return sent
