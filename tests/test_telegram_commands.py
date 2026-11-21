"""Telegram bot commands: schedule, next lesson, notifications, unlink — with a real store, no network."""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import httpx

from hse_schedule import telegram_commands as commands
from hse_schedule.notification_store import NotificationStore
from hse_schedule.telegram import TelegramBot

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 23, 9, 0, tzinfo=MSK)  # Monday, 09:00 Moscow
EMAIL = "student@example.test"


def lesson(day_offset: int, hour: int, title: str, *, room="Б-118", kind="Семинар", change=None):
    start = (NOW + timedelta(days=day_offset)).replace(hour=hour, minute=30)
    return SimpleNamespace(starts_at=start, ends_at=start + timedelta(minutes=80), title=title, kind=kind, room=room, change=change)


LESSONS = (
    lesson(0, 9, "Эконометрика"),
    lesson(0, 11, "Микроэкономика", change=SimpleNamespace(kind="cancelled", note="Преподаватель на конференции", was_room=None)),
    lesson(1, 13, "История экономических учений", change=SimpleNamespace(kind="room", note=None, was_room="А-210"), room="В-212"),
    lesson(3, 15, "Английский язык", kind=None, room=None),
)


class FakeSchedule:
    def __init__(self, lessons=LESSONS, fail=False):
        self.lessons, self.fail, self.calls = lessons, fail, []

    def get_schedule(self, email, start, finish):
        self.calls.append((email, start, finish))
        if self.fail:
            raise RuntimeError("HSE is down")
        return self.lessons


class FormattingTests(unittest.TestCase):
    def test_today_marks_cancellations(self):
        text = commands.day_text(LESSONS, NOW.date(), NOW.date())
        self.assertTrue(text.startswith("Сегодня, Пн, 23 ноября"))
        self.assertIn("09:30–10:50 Эконометрика\n   семинар · ауд. Б-118", text)
        self.assertIn("❌ ОТМЕНЕНА: 11:30–12:50 Микроэкономика", text)
        self.assertIn("Преподаватель на конференции", text)

    def test_room_change_shows_the_old_room(self):
        text = commands.day_text(LESSONS, NOW.date() + timedelta(days=1), NOW.date())
        self.assertIn("🚪 Другая аудитория", text)
        self.assertIn("(было А-210)", text)

    def test_empty_day_and_week(self):
        self.assertIn("Пар нет", commands.day_text(LESSONS, NOW.date() + timedelta(days=2), NOW.date()))
        week = commands.week_text(LESSONS, NOW.date())
        self.assertEqual(week.count("ноября"), 3)  # three days with lessons
        self.assertIn("Английский язык", week)
        self.assertEqual(commands.week_text((), NOW.date()), "На ближайшие 7 дней пар нет.")

    def test_next_skips_cancelled_and_says_when_running(self):
        self.assertIn("идёт сейчас", commands.next_text(LESSONS, NOW + timedelta(minutes=40)))
        after_first = commands.next_text(LESSONS, NOW.replace(hour=11))
        self.assertIn("История экономических учений", after_first)  # the cancelled 11:30 lesson is skipped
        self.assertIn("Завтра", after_first)

    def test_buttons_and_commands_are_recognised(self):
        self.assertEqual(commands.command_of("📅 Сегодня"), "/today")
        self.assertEqual(commands.command_of("/week@dekanat_bot"), "/week")
        self.assertIsNone(commands.command_of("привет"))


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.store = NotificationStore(self.temporary / "n.sqlite3")
        self.addCleanup(self.store.close)
        self.sent: list[dict] = []
        self.updates: list[dict] = []
        self.next_id = 1

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if request.url.path.endswith("/getUpdates"):
            result = [u for u in self.updates if u["update_id"] >= body["offset"]]
            return httpx.Response(200, json={"ok": True, "result": result})
        self.sent.append(body)
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    def say(self, text: str, chat_id: int = 777) -> str:
        self.updates.append({"update_id": self.next_id, "message": {
            "chat": {"type": "private", "id": chat_id}, "from": {"id": chat_id, "username": "student"}, "text": text}})
        self.next_id += 1
        before = len(self.sent)
        self.bot.poll_once(self.store, NOW.astimezone(timezone.utc), self.schedule)
        replies = self.sent[before:]
        self.assertEqual(len(replies), 1, replies)
        return replies[0]["text"]

    def link(self, chat_id: int = 777) -> None:
        self.store.create_telegram_link(EMAIL, "one_time_link_token_123456", NOW + timedelta(minutes=10))
        self.assertIn("Telegram привязан", self.say("/start one_time_link_token_123456", chat_id))

    @property
    def bot(self) -> TelegramBot:
        if not hasattr(self, "_bot"):
            self._bot = TelegramBot("123456:TEST-token_value", username="dekanat_demo_bot", transport=httpx.MockTransport(self.handler))
        return self._bot

    schedule = FakeSchedule()

    def test_unlinked_chat_gets_instructions_only(self):
        reply = self.say("/today")
        self.assertIn("не привязан", reply)
        self.assertNotIn("Эконометрика", reply)

    def test_linked_chat_sees_its_schedule_with_a_keyboard(self):
        self.link()
        reply = self.say("📅 Сегодня")
        self.assertIn("Эконометрика", reply)
        self.assertEqual(self.sent[-1]["reply_markup"]["keyboard"][0][0]["text"], "📅 Сегодня")
        self.assertEqual(self.schedule.calls[-1][0], EMAIL)  # the account comes from the binding, not from the text
        self.assertIn("История экономических учений", self.say("/tomorrow"))
        self.assertIn("Английский язык", self.say("/week"))
        self.assertIn("Следующая пара", self.say("/next"))

    def test_another_chat_cannot_read_a_linked_schedule(self):
        self.link(777)
        self.assertIn("не привязан", self.say("/today", chat_id=888))

    def test_notifications_and_help(self):
        self.link()
        self.assertIn("Уведомлений пока нет", self.say("/notifications"))
        self.store.publish_notifications(EMAIL, [{"event_key": "moved-l1", "kind": "changed", "title": "Пара перенесена",
                                                  "body": "Эконометрика — на 13:30", "payload": {}}], NOW)
        feed = self.say("/notifications")
        self.assertIn("Пара перенесена", feed)
        self.assertIn("🔵", feed)  # unread in the cabinet
        self.assertIn("непрочитанных в кабинете: 1", feed)
        self.assertIn("/today", self.say("/help"))
        self.assertIn("Не понял", self.say("что там по парам?"))

    def test_unlink_stops_the_chat(self):
        self.link()
        self.assertIn("отвязан", self.say("/unlink"))
        self.assertNotIn("reply_markup", self.sent[-1])
        self.assertIn("не привязан", self.say("/today"))

    def test_schedule_failure_is_a_polite_message(self):
        self.link()
        self.schedule = FakeSchedule(fail=True)
        self.assertIn("Не удалось получить расписание", self.say("/today"))
        self.schedule = FakeSchedule()

    def test_expired_link_explains_how_to_get_a_new_one(self):
        self.store.create_telegram_link(EMAIL, "one_time_link_token_123456", NOW - timedelta(minutes=1))
        reply = self.say("/start one_time_link_token_123456")
        self.assertIn("одноразовая", reply)
        self.assertIsNone(self.store.telegram_email("777"))

    def test_menu_is_set_once(self):
        self.bot.set_menu()
        self.bot.set_menu()
        methods = [b for b in self.sent if "commands" in b]
        self.assertEqual(len(methods), 2)  # Russian and default lists, only once
        self.assertIn("today", [c["command"] for c in methods[0]["commands"]])


if __name__ == "__main__":
    unittest.main()
