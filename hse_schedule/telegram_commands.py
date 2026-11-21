"""What the bot answers in a linked private chat: schedule, notifications, help, unlink.

The chat is identified only by its own chat id, bound earlier through a one-time
link from the cabinet; nothing a user types can switch the account. Texts are
plain (no Markdown), so nothing from the timetable can break the formatting.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
WEEKDAYS = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]

BUTTONS = {
    "📅 Сегодня": "/today",
    "📆 Завтра": "/tomorrow",
    "🗓 Неделя": "/week",
    "⏭ Следующая пара": "/next",
    "🔔 Уведомления": "/notifications",
    "❓ Помощь": "/help",
}
KEYBOARD = {
    "keyboard": [[{"text": "📅 Сегодня"}, {"text": "📆 Завтра"}],
                 [{"text": "🗓 Неделя"}, {"text": "⏭ Следующая пара"}],
                 [{"text": "🔔 Уведомления"}, {"text": "❓ Помощь"}]],
    "resize_keyboard": True,
    "is_persistent": True,
}
COMMANDS = [
    {"command": "today", "description": "Пары на сегодня"},
    {"command": "tomorrow", "description": "Пары на завтра"},
    {"command": "week", "description": "Расписание на 7 дней"},
    {"command": "next", "description": "Следующая пара"},
    {"command": "notifications", "description": "Последние уведомления"},
    {"command": "help", "description": "Что умеет бот"},
    {"command": "unlink", "description": "Отвязать аккаунт"},
]
HELP = (
    "Я бот «Цифрового деканата» (учебный концепт, не официальный сервис вуза).\n\n"
    "📅 /today — пары на сегодня\n"
    "📆 /tomorrow — на завтра\n"
    "🗓 /week — на 7 дней\n"
    "⏭ /next — следующая пара\n"
    "🔔 /notifications — последние уведомления\n"
    "/unlink — отвязать аккаунт\n\n"
    "Сюда же приходят уведомления о переносах, отменах и заменах аудиторий — если они включены в кабинете."
)
NOT_LINKED = (
    "Этот чат не привязан к кабинету.\n\n"
    "Откройте личный кабинет → «Уведомления» → «Привязать Telegram» и перейдите по ссылке — она одноразовая и действует 10 минут."
)
EXPIRED = "Ссылка не сработала: она одноразовая и действует 10 минут. Получите новую в кабинете → «Уведомления» → «Привязать Telegram»."
LINKED = (
    "Telegram привязан ✅\n\n"
    "Теперь здесь можно смотреть расписание и получать уведомления (включаются в кабинете → «Уведомления»).\n"
    "Кнопки внизу — быстрые команды."
)


def day_title(day: date, today: date) -> str:
    prefix = "Сегодня, " if day == today else "Завтра, " if day == today + timedelta(days=1) else ""
    return f"{prefix}{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def _time(value: datetime) -> str:
    return value.astimezone(MOSCOW).strftime("%H:%M")


def lesson_line(lesson) -> str:
    parts = [f"{_time(lesson.starts_at)}–{_time(lesson.ends_at)} {lesson.title}"]
    details = [d for d in ((lesson.kind or "").lower(), lesson.room and f"ауд. {lesson.room}") if d]
    if details:
        parts.append(" · ".join(details))
    line = "\n   ".join(parts)
    change = lesson.change
    if change is not None:
        if change.kind == "cancelled":
            line = f"❌ ОТМЕНЕНА: {line}"
        elif change.kind == "moved":
            line = f"🔁 Перенос: {line}"
        elif change.kind == "room":
            line = f"🚪 Другая аудитория: {line}" + (f" (было {change.was_room})" if change.was_room else "")
        if change.note:
            line += f"\n   {change.note}"
    return line


def day_text(lessons, day: date, today: date) -> str:
    items = [lesson for lesson in lessons if lesson.starts_at.astimezone(MOSCOW).date() == day]
    if not items:
        return f"{day_title(day, today)}\nПар нет 🎉"
    return f"{day_title(day, today)}\n\n" + "\n\n".join(lesson_line(lesson) for lesson in items)


def week_text(lessons, today: date) -> str:
    blocks = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        items = [lesson for lesson in lessons if lesson.starts_at.astimezone(MOSCOW).date() == day]
        if items:
            blocks.append(f"{day_title(day, today)}\n" + "\n".join(lesson_line(lesson) for lesson in items))
    return "\n\n".join(blocks) if blocks else "На ближайшие 7 дней пар нет."


def next_text(lessons, now: datetime) -> str:
    upcoming = [lesson for lesson in lessons if lesson.ends_at > now and (lesson.change is None or lesson.change.kind != "cancelled")]
    if not upcoming:
        return "В ближайшие 7 дней пар нет."
    lesson = min(upcoming, key=lambda item: item.starts_at)
    today = now.astimezone(MOSCOW).date()
    day = lesson.starts_at.astimezone(MOSCOW).date()
    when = "идёт сейчас" if lesson.starts_at <= now else day_title(day, today)
    return f"Следующая пара ({when}):\n\n{lesson_line(lesson)}"


def notifications_text(feed: dict) -> str:
    items = feed.get("items") or []
    if not items:
        return "Уведомлений пока нет. Они появятся, когда в расписании что-то изменится."
    lines = [f"Последние уведомления (непрочитанных в кабинете: {feed.get('unread_count', 0)}):"]
    for item in items[:5]:
        mark = "🔵 " if not item.get("read_at") else ""
        lines.append(f"\n{mark}{item.get('title', '')}\n{item.get('body', '')}")
    return "\n".join(lines)[:4000]


def command_of(text: str) -> str | None:
    """«/today», «/today@bot» or a keyboard button → «/today»; anything else → None."""
    text = text.strip()
    if text in BUTTONS:
        return BUTTONS[text]
    if text.startswith("/"):
        return text.split()[0].split("@")[0].lower()
    return None


def answer(command: str | None, *, email: str, schedule, store, now: datetime, unlink) -> str:
    """The reply for a linked chat. schedule may be None (then the schedule part says so)."""
    today = now.astimezone(MOSCOW).date()
    if command in ("/today", "/tomorrow", "/week", "/next", "/schedule"):
        if schedule is None:
            return "Расписание сейчас недоступно. Попробуйте позже."
        try:
            lessons = schedule.get_schedule(email, today, today + timedelta(days=6))
        except Exception:
            return "Не удалось получить расписание. Попробуйте чуть позже."
        if command == "/today":
            return day_text(lessons, today, today)
        if command == "/tomorrow":
            return day_text(lessons, today + timedelta(days=1), today)
        if command == "/next":
            return next_text(lessons, now)
        return week_text(lessons, today)
    if command == "/notifications":
        return notifications_text(store.list_notifications(email, limit=5))
    if command == "/unlink":
        unlink()
        return "Аккаунт отвязан: уведомления сюда больше не придут. Привязать снова можно в кабинете."
    if command in ("/start", "/help", "/menu"):
        return HELP
    return "Не понял команду. " + HELP.split("\n\n", 1)[1]
