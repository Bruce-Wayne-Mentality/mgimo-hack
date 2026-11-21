"""Telegram bot: plain schedule, home message, one panel with tabs, lesson timer — real store, no network."""

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
from hse_schedule.directory import Student
from hse_schedule.models import Group
from hse_schedule.notification_store import NotificationStore
from hse_schedule.telegram import TelegramBot

MSK = ZoneInfo("Europe/Moscow")
NOW = datetime(2026, 11, 22, 20, 0, tzinfo=MSK)  # Sunday evening: «завтра» is Monday, 23 November
EMAIL = "anna@example.test"
GROUP = Group(oid="2510", name="ЭК-25-1")


def lesson(day: int, hh: int, mm: int, title: str, *, kind="Лекция", room="305", teachers=(), subgroup=None,
           change=None, minutes=90, lesson_id=None):
    start = datetime(2026, 11, day, hh, mm, tzinfo=MSK)
    return SimpleNamespace(id=lesson_id or f"{title}-{day}-{hh}{mm}-{subgroup}", starts_at=start,
                           ends_at=start + timedelta(minutes=minutes), title=title, kind=kind, room=room,
                           teachers=tuple(teachers), subgroup=subgroup, groups=(GROUP,), change=change)


MONDAY = (
    lesson(23, 9, 30, "Высшая математика", room="305", minutes=80),
    lesson(23, 11, 10, "Информатика", kind="Практическое занятие", room="412", teachers=("Иванов Иван Иванович",), minutes=80),
    lesson(23, 13, 0, "Иностранный язык", kind=None, room="201", subgroup="1", minutes=80),
    lesson(23, 13, 0, "Иностранный язык", kind=None, room="204", subgroup="2", minutes=80),
    lesson(23, 14, 40, "Физкультура", kind="Семинар", change=SimpleNamespace(kind="cancelled", note=None, was_room=None)),
)


class FakeSchedule:
    def __init__(self, lessons=MONDAY):
        self.lessons, self.calls = lessons, []
        self.directory = SimpleNamespace(get=lambda email: Student(email=email, name="Анна Миронова", group_oids=("2510",)))

    def get_schedule(self, email, start, finish):
        self.calls.append(email)
        return self.lessons


class FormatTests(unittest.TestCase):
    def test_tomorrow_looks_like_the_requested_example(self):
        text = commands.day_text(MONDAY, NOW.date() + timedelta(days=1), NOW.date())
        self.assertEqual(text, (
            "Расписание на завтра (Понедельник, 23 ноября)\n\n"
            "1 пара (09:30 – 10:50)\nВысшая математика (лекция)\nауд. 305\n\n"
            "2 пара (11:10 – 12:30)\nИнформатика (практика)\nауд. 412, Иванов И.И.\n\n"
            "3 пара (13:00 – 14:20)\nИностранный язык\nауд. 201 (1 подгруппа) / 204 (2 подгруппа)"))

    def test_no_change_marks_and_cancelled_lessons_are_hidden(self):
        moved = lesson(24, 12, 50, "Микроэкономика", change=SimpleNamespace(kind="moved", note="перенос", was_room=None))
        room = lesson(24, 9, 30, "Эконометрика", room="Б-118", change=SimpleNamespace(kind="room", note="ремонт", was_room="А-210"))
        text = commands.week_text(MONDAY + (moved, room), NOW.date() + timedelta(days=1))
        for word in ("Перенос", "перенос", "было", "ремонт", "ОТМЕН", "Физкультура", "А-210"):
            self.assertNotIn(word, text)
        self.assertIn("3 пара (12:50 – 14:20)\nМикроэкономика (лекция)", text)  # a moved lesson keeps its slot number
        self.assertIn("ауд. Б-118", text)

    def test_empty_day(self):
        self.assertTrue(commands.day_text(MONDAY, NOW.date(), NOW.date()).endswith("Пар нет 🎉"))
        self.assertIn("пар нет", commands.week_text((), NOW.date()))

    def test_home_shows_name_group_unread_and_last_unread(self):
        feed = {"unread_count": 2, "items": [
            {"title": "Расписание изменилось", "body": "Микроэкономика — ауд. Б-214", "read_at": None},
            {"title": "Старое", "body": "...", "read_at": "x"}]}
        text = commands.home_text(commands.Profile("Анна Миронова", "ЭК-25-1"), feed, None)
        self.assertIn("Здравствуйте, Анна Миронова!", text)
        self.assertIn("Группа: ЭК-25-1", text)
        self.assertIn("Непрочитанных уведомлений: 2", text)
        self.assertIn("Последнее: Расписание изменилось\nМикроэкономика — ауд. Б-214", text)
        self.assertIn("Напоминание перед парой: выключено", text)

    def test_timer_values(self):
        self.assertEqual([commands.timer_value(t) for t in ("25", "за 15 минут", "10 мин", "0", "500", "привет")],
                         [25, 15, 10, None, None, None])


class BotTests(unittest.TestCase):
    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.store = NotificationStore(self.temporary / "n.sqlite3")
        self.addCleanup(self.store.close)
        self.calls: list[tuple[str, dict]] = []
        self.updates: list[dict] = []
        self.next_update, self.next_message = 1, 100
        self.schedule = FakeSchedule()
        self.bot = TelegramBot("123456:TEST-token_value", username="dekanat_demo_bot", transport=httpx.MockTransport(self.handler))

    def handler(self, request: httpx.Request) -> httpx.Response:
        method = request.url.path.rsplit("/", 1)[-1]
        body = json.loads(request.content)
        if method == "getUpdates":
            return httpx.Response(200, json={"ok": True, "result": [u for u in self.updates if u["update_id"] >= body["offset"]]})
        self.calls.append((method, body))
        if method == "sendMessage":
            self.next_message += 1
            return httpx.Response(200, json={"ok": True, "result": {"message_id": self.next_message}})
        return httpx.Response(200, json={"ok": True, "result": True})

    def poll(self, now=NOW):
        before = len(self.calls)
        self.bot.poll_once(self.store, now.astimezone(timezone.utc), self.schedule)
        return self.calls[before:]

    def say(self, text: str, chat_id: int = 777):
        self.updates.append({"update_id": self.next_update, "message": {
            "message_id": 5000 + self.next_update, "chat": {"type": "private", "id": chat_id},
            "from": {"id": chat_id, "username": "student"}, "text": text}})
        self.next_update += 1
        return self.poll()

    def press(self, data: str, message_id: int, chat_id: int = 777):
        self.updates.append({"update_id": self.next_update, "callback_query": {
            "id": f"cb{self.next_update}", "data": data, "from": {"id": chat_id},
            "message": {"message_id": message_id, "chat": {"type": "private", "id": chat_id}}}})
        self.next_update += 1
        return self.poll()

    def link(self):
        self.store.create_telegram_link(EMAIL, "one_time_link_token_123456", NOW + timedelta(minutes=10))
        calls = self.say("/start one_time_link_token_123456")
        texts = [b["text"] for m, b in calls if m == "sendMessage"]
        self.assertIn("Telegram привязан ✅", texts)
        return self.store.telegram_panel("777")

    def test_unlinked_chat_gets_instructions_only(self):
        calls = self.say("/today")
        self.assertEqual([m for m, _ in calls], ["sendMessage"])
        self.assertIn("не привязан", calls[0][1]["text"])

    def test_linking_shows_the_home_panel_with_tabs(self):
        panel = self.link()
        last = [b for m, b in self.calls if m == "sendMessage"][-1]
        self.assertEqual(last["reply_markup"]["inline_keyboard"][0][1]["callback_data"], "tab:today")
        self.assertIn("Здравствуйте, Анна Миронова!", last["text"])
        self.assertIn("Группа: ЭК-25-1", last["text"])
        self.assertIsNotNone(panel)

    def test_tabs_rewrite_the_same_message(self):
        panel = self.link()
        calls = self.press("tab:tomorrow", panel)
        methods = [m for m, _ in calls]
        self.assertNotIn("sendMessage", methods)  # nothing new in the chat
        edit = next(b for m, b in calls if m == "editMessageText")
        self.assertEqual(edit["message_id"], panel)
        self.assertTrue(edit["text"].startswith("Расписание на завтра (Понедельник, 23 ноября)"))
        self.assertIn("answerCallbackQuery", methods)
        week = next(b for m, b in self.press("tab:week", panel) if m == "editMessageText")
        self.assertIn("Расписание на неделю", week["text"])

    def test_typed_command_is_deleted_and_the_old_panel_replaced(self):
        old_panel = self.link()
        calls = self.say("/tomorrow")
        deleted = [b["message_id"] for m, b in calls if m == "deleteMessage"]
        self.assertIn(old_panel, deleted)  # the previous tab is gone
        self.assertTrue(any(i >= 5000 for i in deleted))  # and the typed command too
        new_panel = self.store.telegram_panel("777")
        self.assertNotEqual(new_panel, old_panel)

    def test_another_chat_cannot_press_someone_elses_tabs(self):
        panel = self.link()
        calls = self.press("tab:today", panel, chat_id=888)
        self.assertNotIn("editMessageText", [m for m, _ in calls])
        self.assertEqual(self.schedule.calls, [EMAIL])  # only the owner's home panel loaded the schedule

    def test_timer_is_off_by_default_and_set_by_the_user(self):
        panel = self.link()
        self.assertIsNone(self.store.telegram_timer(EMAIL))
        calls = self.press("timer:15", panel)
        self.assertEqual(self.store.telegram_timer(EMAIL), 15)
        self.assertEqual(next(b for m, b in calls if m == "answerCallbackQuery")["text"], "Напоминание за 15 мин")
        self.say("25")  # a custom value typed by the user
        self.assertEqual(self.store.telegram_timer(EMAIL), 25)
        self.press("timer:0", self.store.telegram_panel("777"))
        self.assertIsNone(self.store.telegram_timer(EMAIL))

    def test_reminder_is_sent_once_and_only_when_on(self):
        self.link()
        before_first = datetime(2026, 11, 23, 9, 20, tzinfo=MSK)
        self.assertEqual(self.bot.send_reminders(self.store, before_first, self.schedule), 0)  # off by default
        self.store.set_telegram_timer(EMAIL, 15)
        self.assertEqual(self.bot.send_reminders(self.store, datetime(2026, 11, 23, 9, 10, tzinfo=MSK), self.schedule), 0)
        self.assertEqual(self.bot.send_reminders(self.store, before_first, self.schedule), 1)
        reminder = [b["text"] for m, b in self.calls if m == "sendMessage"][-1]
        self.assertEqual(reminder, "⏰ Через 15 мин — пара в 09:30\nВысшая математика (лекция)\nауд. 305")
        self.assertEqual(self.bot.send_reminders(self.store, before_first + timedelta(minutes=2), self.schedule), 0)  # once
        cancelled_time = datetime(2026, 11, 23, 14, 30, tzinfo=MSK)
        self.assertEqual(self.bot.send_reminders(self.store, cancelled_time, self.schedule), 0)  # cancelled lesson: nothing

    def test_unlink_removes_the_panel_and_stops_reminders(self):
        panel = self.link()
        self.store.set_telegram_timer(EMAIL, 15)
        calls = self.say("/unlink")
        self.assertIn(panel, [b["message_id"] for m, b in calls if m == "deleteMessage"])
        self.assertEqual(self.store.telegram_timers(), [])
        self.assertIn("не привязан", self.say("/today")[0][1]["text"])

    def test_expired_link(self):
        self.store.create_telegram_link(EMAIL, "one_time_link_token_123456", NOW - timedelta(minutes=1))
        calls = self.say("/start one_time_link_token_123456")
        self.assertIn("одноразовая", calls[0][1]["text"])
        self.assertIsNone(self.store.telegram_email("777"))


if __name__ == "__main__":
    unittest.main()
