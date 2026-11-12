"""Compare successful timetable snapshots and create durable notifications."""

from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .errors import ScheduleError
from .models import Lesson
from .notification_store import NotificationStore
from .service import ScheduleService

logger = logging.getLogger(__name__)


def _hash(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def _groups(lesson: dict) -> tuple[str, ...]:
    return tuple(sorted(group["oid"] for group in lesson.get("groups", [])))


def _identity(lesson: dict) -> str:
    if lesson.get("source_lesson_id"):
        return "source:" + lesson["source_lesson_id"]
    # Without a provider ID, this is the best available stable identity.
    return "content:" + _hash([lesson["title"], lesson.get("kind"), _groups(lesson)])


def reminder_key(lesson: dict) -> str:
    """Room/teacher changes must not repeat a reminder for the same occurrence."""
    return "reminder:" + _hash([_identity(lesson), lesson["starts_at"], _groups(lesson)])


def _details(lesson: dict) -> str:
    start = datetime.fromisoformat(lesson["starts_at"])
    end = datetime.fromisoformat(lesson["ends_at"])
    parts = [lesson["title"], start.strftime("%d.%m %H:%M") + "–" + end.strftime("%H:%M")]
    if lesson.get("kind"):
        parts.append(lesson["kind"])
    if lesson.get("teachers"):
        parts.append(", ".join(lesson["teachers"]))
    if lesson.get("room"):
        parts.append("ауд. " + lesson["room"])
    if lesson.get("building"):
        parts.append(lesson["building"])
    return " · ".join(parts)


def _reminder(lesson: dict) -> dict:
    starts = datetime.fromisoformat(lesson["starts_at"])
    return {
        "kind": "reminder",
        "title": "Скоро начнётся пара",
        "body": _details(lesson),
        "payload": {"lesson": lesson, "scheduled_for": (starts - timedelta(minutes=10)).isoformat()},
        "event_key": reminder_key(lesson),
        "expires_at": starts.isoformat(),
    }


def _changes(before: list[dict], after: list[dict]) -> list[tuple[str, dict | None, dict | None]]:
    """Match exact occurrences first, then changes under the provider's ID.

    Source IDs can recur across days, while normalized lesson IDs change with
    the room/time. Matching by normalized ID would misreport every room change
    as a cancellation and a new class.
    """
    previous: dict[str, list[dict]] = defaultdict(list)
    current: dict[str, list[dict]] = defaultdict(list)
    for lesson in before:
        previous[_identity(lesson)].append(lesson)
    for lesson in after:
        current[_identity(lesson)].append(lesson)
    changes = []
    for identity in sorted(previous.keys() | current.keys()):
        old = sorted(previous[identity], key=lambda item: (item["starts_at"], item["id"]))
        new = sorted(current[identity], key=lambda item: (item["starts_at"], item["id"]))
        for lesson in old[:]:
            if lesson in new:
                old.remove(lesson)
                new.remove(lesson)
        # Keep repeated IDs on separate dates, and parallel subgroups distinct.
        for same in (
            lambda a, b: a["date"] == b["date"] and _groups(a) == _groups(b),
            lambda a, b: a["date"] == b["date"],
        ):
            for lesson in old[:]:
                match = next((candidate for candidate in new if same(lesson, candidate)), None)
                if match is not None:
                    old.remove(lesson)
                    new.remove(match)
                    changes.append(("schedule_changed", lesson, match))
        # A single remaining occurrence can have moved to another day.
        if len(old) == len(new) == 1:
            changes.append(("schedule_changed", old.pop(), new.pop()))
        changes.extend(("schedule_cancelled", lesson, None) for lesson in old)
        changes.extend(("schedule_added", None, lesson) for lesson in new)
    return changes


class NotificationEngine:
    def __init__(self, service: ScheduleService, store: NotificationStore) -> None:
        self.service = service
        self.store = store

    def refresh_schedules(self, now: datetime | None = None) -> dict:
        now = now or datetime.now(timezone.utc)
        start = now.astimezone(ZoneInfo(self.service.timezone)).date()
        finish = start + timedelta(days=6)
        refreshed = failed = 0
        for student in self.service.directory.list_students():
            try:
                lessons = self.service.get_schedule(student.email, start, finish)
                if self.observe(student.email, start, finish, lessons, now):
                    refreshed += 1
            except (ScheduleError, ValueError):
                # A failed fetch must never turn cached classes into cancellations.
                logger.warning("Timetable refresh failed; retaining the last successful snapshot.")
                failed += 1
        return {"refreshed": refreshed, "failed": failed}

    def observe(
        self,
        email: str,
        start: date,
        finish: date,
        lessons: tuple[Lesson, ...],
        now: datetime,
    ) -> bool:
        rows = [lesson.to_dict() for lesson in lessons]
        previous = self.store.load_snapshot(email)
        drafts = []
        if previous is not None:
            # New dates at the edge of a rolling window are a baseline, not
            # additions; old dates falling out of the window are not cancelled.
            common_start = max(start, date.fromisoformat(previous["start"]))
            common_finish = min(finish, date.fromisoformat(previous["finish"]))
            old_rows = [row for row in previous["lessons"] if common_start.isoformat() <= row["date"] <= common_finish.isoformat()]
            new_rows = [row for row in rows if common_start.isoformat() <= row["date"] <= common_finish.isoformat()]
            for kind, before, after in _changes(old_rows, new_rows):
                titles = {
                    "schedule_added": "В расписании появилась пара",
                    "schedule_cancelled": "Пара отменена",
                    "schedule_changed": "Расписание изменилось",
                }
                if before is not None and after is not None:
                    body = "Было: " + _details(before) + ". Теперь: " + _details(after)
                else:
                    body = _details(after if after is not None else before)
                drafts.append({
                    "kind": kind,
                    "title": titles[kind],
                    "body": body,
                    "payload": {"before": before, "after": after},
                    "event_key": "change:" + _hash([previous["version"], kind, before, after]),
                    "expires_at": (now + timedelta(days=1)).isoformat(),
                })
        saved = self.store.commit_observation(
            email,
            previous["version"] if previous else None,
            start=start, finish=finish, lessons=rows, notifications=drafts, now=now,
        )
        if saved:
            version = (previous["version"] if previous else 0) + 1
            self.store.cancel_stale_reminders(
                email, {reminder_key(row) for row in rows}, expected_version=version,
            )
            self.store.update_reminder_details(
                email, [_reminder(row) for row in rows], expected_version=version,
            )
        return saved

    def emit_reminders(self, now: datetime | None = None) -> int:
        now = now or datetime.now(timezone.utc)
        observed = 0
        for student in self.service.directory.list_students():
            snapshot = self.store.load_snapshot(student.email)
            if snapshot is None:
                continue
            drafts = []
            for lesson in snapshot["lessons"]:
                starts = datetime.fromisoformat(lesson["starts_at"])
                if student.student_oid is None and not set(_groups(lesson)).intersection(student.group_oids):
                    continue
                if starts - timedelta(minutes=10) <= now < starts:
                    drafts.append(_reminder(lesson))
            if drafts and self.store.publish_notifications(
                student.email, drafts, now, expected_version=snapshot["version"]
            ):
                observed += 1
        return observed
