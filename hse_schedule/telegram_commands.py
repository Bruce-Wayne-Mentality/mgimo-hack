"""What the bot shows in a linked private chat.

One panel message with tabs under it (inline buttons): pressing a tab rewrites
the same message, so the chat does not fill up. The schedule is plain — the
current state only: cancelled lessons are not shown, moved ones stand at their
new time, the room is the current one. No «перенос» or «было» marks; changes
arrive as separate notifications.

The chat's account comes only from its binding; nothing typed can switch it.
Texts are plain (no Markdown), so nothing from the timetable breaks formatting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

MOSCOW = ZoneInfo("Europe/Moscow")
WEEKDAYS = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница", "Суббота", "Воскресенье"]
MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
# The bell schedule: a lesson's number is the closest start (a lesson moved to 12:50 stays «3 пара»).
BELLS = [time(9, 30), time(11, 10), time(13, 0), time(14, 40), time(16, 20), time(18, 10), time(19, 40)]
KINDS = {"лекция": "лекция", "семинар": "семинар", "практическое занятие": "практика", "практика": "практика",
         "лабораторная работа": "лабораторная", "консультация": "консультация", "экзамен": "экзамен", "зачёт": "зачёт"}
TIMER_CHOICES = (5, 10, 15, 30, 60)
TIMER_MAX = 180

TABS = [
    [("🏠 Главная", "home"), ("📅 Сегодня", "today"), ("📆 Завтра", "tomorrow")],
    [("🗓 Неделя", "week"), ("🔔 Уведомления", "notifications"), ("⏰ Таймер", "timer")],
]
COMMANDS = [
    {"command": "start", "description": "Главная"},
    {"command": "today", "description": "Расписание на сегодня"},
    {"command": "tomorrow", "description": "Расписание на завтра"},
    {"command": "week", "description": "Расписание на неделю"},
    {"command": "notifications", "description": "Уведомления"},
    {"command": "timer", "description": "Напоминание перед парой"},
    {"command": "unlink", "description": "Отвязать аккаунт"},
]
ALIASES = {"/start": "home", "/menu": "home", "/help": "home", "/today": "today", "/tomorrow": "tomorrow",
           "/week": "week", "/schedule": "week", "/notifications": "notifications", "/timer": "timer", "/unlink": "unlink",
           # buttons of the earlier keyboard, so old chats keep working
           "📅 Сегодня": "today", "📆 Завтра": "tomorrow", "🗓 Неделя": "week", "🔔 Уведомления": "notifications",
           "❓ Помощь": "home", "⏭ Следующая пара": "today"}

NOT_LINKED = (
    "Этот чат не привязан к кабинету.\n\n"
    "Откройте личный кабинет → «Уведомления» → «Привязать Telegram» и перейдите по ссылке — она одноразовая и действует 10 минут."
)
EXPIRED = "Ссылка не сработала: она одноразовая и действует 10 минут. Получите новую в кабинете → «Уведомления» → «Привязать Telegram»."
UNLINKED = "Аккаунт отвязан: уведомления и напоминания сюда больше не придут. Привязать снова можно в кабинете."


@dataclass
class Profile:
    name: str
    group: str | None


def keyboard(active: str | None = None, *, extra: list[list[tuple[str, str]]] = ()) -> dict:
    rows = [[{"text": ("• " + label + " •") if key == active else label, "callback_data": f"tab:{key}"} for label, key in row]
            for row in TABS]
    rows = [[{"text": label, "callback_data": data} for label, data in row] for row in extra] + rows
    return {"inline_keyboard": rows}


def tab_of(text: str) -> str | None:
    """A typed command or an old keyboard button → the tab; anything else → None."""
    text = text.strip()
    if text in ALIASES:
        return ALIASES[text]
    if text.startswith("/"):
        return ALIASES.get(text.split()[0].split("@")[0].lower())
    return None


def timer_value(text: str) -> int | None:
    """«15», «15 мин», «за 15 минут» → 15 when 1…TIMER_MAX."""
    match = re.fullmatch(r"(?:за\s*)?(\d{1,3})\s*(?:м|мин|минут[аы]?)?\.?", text.strip().lower())
    if not match:
        return None
    value = int(match.group(1))
    return value if 1 <= value <= TIMER_MAX else None


# ---- schedule ------------------------------------------------------------------------------

def day_name(day: date) -> str:
    return f"{WEEKDAYS[day.weekday()]}, {day.day} {MONTHS[day.month - 1]}"


def _clock(value: datetime) -> str:
    return value.astimezone(MOSCOW).strftime("%H:%M")


def pair_number(start: datetime) -> int | None:
    local = start.astimezone(MOSCOW)
    minutes = local.hour * 60 + local.minute
    best = min(range(len(BELLS)), key=lambda i: abs(BELLS[i].hour * 60 + BELLS[i].minute - minutes))
    gap = abs(BELLS[best].hour * 60 + BELLS[best].minute - minutes)
    return best + 1 if gap <= 40 else None


def short_name(full: str) -> str:
    """«Корнилова Тамара Андреевна» → «Корнилова Т.А.»."""
    parts = full.split()
    if len(parts) < 2:
        return full
    return parts[0] + " " + "".join(p[0] + "." for p in parts[1:3] if p)


def _kind(kind: str | None) -> str | None:
    if not kind:
        return None
    return KINDS.get(kind.strip().lower(), kind.strip().lower())


def _visible(lessons, day: date) -> list:
    return sorted((lesson for lesson in lessons
                   if lesson.starts_at.astimezone(MOSCOW).date() == day
                   and not (lesson.change is not None and lesson.change.kind == "cancelled")),
                  key=lambda lesson: (lesson.starts_at, lesson.subgroup or ""))


def _pairs_text(lessons, day: date) -> str:
    items = _visible(lessons, day)
    if not items:
        return "Пар нет 🎉"
    blocks, ordinal = [], 0
    groups: list[list] = []
    for lesson in items:  # parallel subgroups of the same lesson are one pair
        if groups and groups[-1][0].starts_at == lesson.starts_at and groups[-1][0].title == lesson.title:
            groups[-1].append(lesson)
        else:
            groups.append([lesson])
    for group in groups:
        first = group[0]
        ordinal += 1
        number = pair_number(first.starts_at) or ordinal
        kind = _kind(first.kind)
        title = f"{first.title} ({kind})" if kind else first.title
        if len(group) > 1 and any(lesson.subgroup for lesson in group):
            place = " / ".join(f"{lesson.room or '—'} ({lesson.subgroup} подгруппа)" for lesson in group)
            where = f"ауд. {place}"
        else:
            teachers = ", ".join(short_name(t) for t in (getattr(first, "teachers", None) or ()) if t)
            where = ", ".join(p for p in ((f"ауд. {first.room}" if first.room else None), teachers or None) if p)
        lines = [f"{number} пара ({_clock(first.starts_at)} – {_clock(first.ends_at)})", title]
        if where:
            lines.append(where)
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def day_text(lessons, day: date, today: date) -> str:
    when = "сегодня" if day == today else "завтра" if day == today + timedelta(days=1) else None
    head = f"Расписание на {when} ({day_name(day)})" if when else f"Расписание ({day_name(day)})"
    return f"{head}\n\n{_pairs_text(lessons, day)}"


def week_text(lessons, today: date) -> str:
    blocks = []
    for offset in range(7):
        day = today + timedelta(days=offset)
        if _visible(lessons, day):
            blocks.append(f"— {day_name(day)} —\n\n{_pairs_text(lessons, day)}")
    if not blocks:
        return "Расписание на неделю\n\nНа ближайшие 7 дней пар нет."
    return "Расписание на неделю\n\n" + "\n\n".join(blocks)


# ---- home, notifications, timer ------------------------------------------------------------

def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def home_text(profile: Profile, feed: dict, timer: int | None) -> str:
    first_unread = next((item for item in feed.get("items") or [] if not item.get("read_at")), None)
    lines = [f"👋 Здравствуйте, {profile.name}!", f"Группа: {profile.group or '—'}", ""]
    unread = int(feed.get("unread_count") or 0)
    lines.append(f"🔔 Непрочитанных уведомлений: {unread}")
    if first_unread:
        lines.append(f"Последнее: {first_unread.get('title', '')}\n{_clip(first_unread.get('body', ''), 300)}")
    lines += ["", f"⏰ Напоминание перед парой: {timer_label(timer)}", "", "Выберите вкладку ниже."]
    return "\n".join(lines)


def notifications_text(feed: dict) -> str:
    items = feed.get("items") or []
    if not items:
        return "🔔 Уведомления\n\nУведомлений пока нет. Они появятся, когда в расписании что-то изменится."
    lines = [f"🔔 Уведомления · непрочитанных: {feed.get('unread_count', 0)}"]
    for item in items[:5]:
        mark = "🔵 " if not item.get("read_at") else ""
        lines.append(f"\n{mark}{item.get('title', '')}\n{_clip(item.get('body', ''), 400)}")
    return "\n".join(lines)[:4000]


def timer_label(minutes: int | None) -> str:
    return f"за {minutes} мин" if minutes else "выключено"


def timer_text(minutes: int | None) -> str:
    return (
        "⏰ Напоминание перед парой\n\n"
        f"Сейчас: {timer_label(minutes)}.\n\n"
        "Выберите время кнопкой или напишите своё число минут (от 1 до 180) — например, 25."
    )


def timer_buttons(minutes: int | None) -> list[list[tuple[str, str]]]:
    choices = [((f"✓ {m} мин" if m == minutes else f"{m} мин"), f"timer:{m}") for m in TIMER_CHOICES]
    return [choices[:3], choices[3:] + [("✓ Выключить" if not minutes else "Выключить", "timer:0")]]


def reminder_text(lesson, minutes: int) -> str:
    kind = _kind(lesson.kind)
    title = f"{lesson.title} ({kind})" if kind else lesson.title
    where = f"ауд. {lesson.room}" if lesson.room else ""
    return "\n".join(p for p in (f"⏰ Через {minutes} мин — пара в {_clock(lesson.starts_at)}", title, where) if p)


def render(tab: str, *, profile: Profile, lessons, feed: dict, timer: int | None, now: datetime) -> tuple[str, dict]:
    """(text, inline keyboard) of a tab."""
    today = now.astimezone(MOSCOW).date()
    if tab == "today":
        return day_text(lessons, today, today), keyboard(tab)
    if tab == "tomorrow":
        return day_text(lessons, today + timedelta(days=1), today), keyboard(tab)
    if tab == "week":
        return week_text(lessons, today), keyboard(tab)
    if tab == "notifications":
        return notifications_text(feed), keyboard(tab)
    if tab == "timer":
        return timer_text(timer), keyboard(tab, extra=timer_buttons(timer))
    return home_text(profile, feed, timer), keyboard("home")
