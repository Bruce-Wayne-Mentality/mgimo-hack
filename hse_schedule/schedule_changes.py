"""FR-STF-5: the deanery moves, cancels or re-rooms a lesson; students see
«было → стало» and get a notification (the existing timetable monitor
notices the difference within a minute).

Edits are stored in lesson_changes and kept in an in-memory overlay that
ScheduleService applies on top of the source timetable.
"""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import replace
from datetime import date, datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy import CheckConstraint, ForeignKey, String, Text, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .accounts.models import AuditLog, StudyGroup, User
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Base, Database, UTCDateTime, utcnow, uuid7
from .models import Lesson, LessonChange as Change

MOSCOW = ZoneInfo("Europe/Moscow")
KIND_LABELS = {"moved": "Перенесена", "cancelled": "Отменена", "room": "Замена аудитории"}


class LessonChange(Base):
    __tablename__ = "lesson_changes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    lesson_id: Mapped[str] = mapped_column(String(128), unique=True)
    group_oid: Mapped[str] = mapped_column(String(32))
    kind: Mapped[str] = mapped_column(String(16))
    title: Mapped[str] = mapped_column(String(200))
    was_starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    was_ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    was_room: Mapped[str | None] = mapped_column(String(64), nullable=True)
    new_starts_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    new_ends_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    new_room: Mapped[str | None] = mapped_column(String(64), nullable=True)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (CheckConstraint("kind IN ('moved', 'cancelled', 'room')", name="kind_known"),)


class Overlay:
    """Thread-safe cache of edits; ScheduleService calls apply() synchronously."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._changes: dict[str, LessonChange] = {}

    @property
    def active(self) -> bool:
        return bool(self._changes)

    def replace_all(self, rows: list[LessonChange]) -> None:
        with self._lock:
            self._changes = {row.lesson_id: row for row in rows}

    def put(self, row: LessonChange) -> None:
        with self._lock:
            self._changes[row.lesson_id] = row

    def drop(self, lesson_id: str) -> None:
        with self._lock:
            self._changes.pop(lesson_id, None)

    def get(self, lesson_id: str) -> LessonChange | None:
        return self._changes.get(lesson_id)

    def apply(self, lessons) -> list[Lesson]:
        with self._lock:
            changes = dict(self._changes)
        result = []
        for lesson in lessons:
            row = changes.get(lesson.id)
            if row is None:
                result.append(lesson)
                continue
            change = Change(kind=row.kind, note=row.note, was_starts_at=lesson.starts_at.isoformat(),
                            was_ends_at=lesson.ends_at.isoformat(), was_room=lesson.room, change_id=str(row.id))
            if row.kind == "cancelled":
                result.append(replace(lesson, change=change))
            elif row.kind == "room":
                result.append(replace(lesson, room=row.new_room or lesson.room, change=change))
            else:
                starts = row.new_starts_at.astimezone(MOSCOW)
                ends = row.new_ends_at.astimezone(MOSCOW)
                result.append(replace(lesson, date=starts.date(), starts_at=starts, ends_at=ends,
                                      room=row.new_room or lesson.room, change=change))
        return result

    def load(self, url: str) -> None:
        """Fill the cache at startup (runs before the server's event loop exists)."""
        async def run() -> list[LessonChange]:
            database = Database(url, pooled=False)
            try:
                async with database.session() as db:
                    return list((await db.scalars(select(LessonChange))).all())
            finally:
                await database.dispose()

        self.replace_all(asyncio.run(run()))


class ChangeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    lesson_id: StrictStr = Field(min_length=1, max_length=128)
    group: StrictStr = Field(min_length=1, max_length=32)
    kind: Literal["moved", "cancelled", "room"]
    new_date: date | None = None
    new_start: StrictStr | None = Field(default=None, pattern=r"^\d{2}:\d{2}$")
    new_room: StrictStr | None = Field(default=None, max_length=64)
    note: StrictStr | None = Field(default=None, max_length=300)


class ScheduleChangeService:
    def __init__(self, database: Database, schedule, overlay: Overlay) -> None:
        self.database = database
        self.schedule = schedule
        self.overlay = overlay

    async def _group(self, user: User, code: str) -> tuple[StudyGroup, str]:
        from .academics.curriculum import SCHEDULE_OIDS

        if not user.is_active or user.role not in ("staff", "admin"):
            raise ApiError(403, "forbidden", "Расписание правит деканат.")
        async with self.database.session() as db:
            group = await db.scalar(select(StudyGroup).where(StudyGroup.code == code))
        if group is None or code not in SCHEDULE_OIDS:
            raise ApiError(404, "not_found", "Группа не найдена.")
        if user.role == "staff" and (user.staff is None or user.staff.faculty_id != group.faculty_id):
            raise ApiError(404, "not_found", "Группа не найдена.")
        return group, SCHEDULE_OIDS[code]

    def _source_week(self, oid: str, start: date, finish: date) -> list[Lesson]:
        lessons = list(self.schedule.source.schedule(start=start - timedelta(days=7), finish=finish + timedelta(days=7), group_oid=oid))
        return [lesson for lesson in self.overlay.apply(lessons) if start <= lesson.date <= finish]

    async def groups(self, user: User) -> list[dict]:
        from .academics.curriculum import SCHEDULE_OIDS

        if not user.is_active or user.role not in ("staff", "admin"):
            raise ApiError(403, "forbidden", "Расписание правит деканат.")
        async with self.database.session() as db:
            rows = list((await db.scalars(select(StudyGroup).order_by(StudyGroup.code))).all())
        return [{"code": g.code, "course": g.course} for g in rows if g.code in SCHEDULE_OIDS
                and (user.role == "admin" or (user.staff and user.staff.faculty_id == g.faculty_id))]

    async def week(self, user: User, code: str, start: date) -> dict:
        _, oid = await self._group(user, code)
        finish = start + timedelta(days=6)
        lessons = await asyncio.to_thread(self._source_week, oid, start, finish)
        return {"group": code, "start": start.isoformat(), "finish": finish.isoformat(),
                "lessons": [lesson.to_dict() for lesson in sorted(lessons, key=lambda item: item.starts_at)]}

    async def change(self, user: User, body: ChangeBody) -> dict:
        _, oid = await self._group(user, body.group)
        if self.overlay.get(body.lesson_id) is not None:
            raise ApiError(409, "already_changed", "У пары уже есть изменение — сначала верните исходное.")
        # Find the original occurrence in the source around today.
        today = datetime.now(MOSCOW).date()
        lessons = await asyncio.to_thread(
            lambda: list(self.schedule.source.schedule(start=today - timedelta(days=7), finish=today + timedelta(days=21), group_oid=oid))
        )
        lesson = next((item for item in lessons if item.id == body.lesson_id), None)
        if lesson is None:
            raise ApiError(404, "not_found", "Пара не найдена (менять можно занятия на ближайшие три недели).")
        row = LessonChange(lesson_id=lesson.id, group_oid=oid, kind=body.kind, title=lesson.title,
                           was_starts_at=lesson.starts_at, was_ends_at=lesson.ends_at, was_room=lesson.room,
                           note=(body.note or "").strip() or None, author_id=user.id, author_name=user.display_name)
        if body.kind == "room":
            if not (body.new_room or "").strip():
                raise ApiError(422, "validation_failed", "Укажите новую аудиторию.", fields={"new_room": "Укажите аудиторию."})
            row.new_room = body.new_room.strip()
        elif body.kind == "moved":
            if body.new_date is None or body.new_start is None:
                raise ApiError(422, "validation_failed", "Укажите новые дату и время.", fields={"new_start": "Укажите время."})
            hours, minutes = (int(part) for part in body.new_start.split(":"))
            if not (8 <= hours <= 21 and minutes < 60):
                raise ApiError(422, "validation_failed", "Пары идут с 08:00 до 22:00.", fields={"new_start": "С 08:00 до 22:00."})
            if abs((body.new_date - lesson.date).days) > 7:
                raise ApiError(422, "validation_failed", "Перенести можно в пределах недели.", fields={"new_date": "В пределах недели."})
            starts = datetime.combine(body.new_date, time(hours, minutes), tzinfo=MOSCOW)
            row.new_starts_at = starts
            row.new_ends_at = starts + (lesson.ends_at - lesson.starts_at)
            row.new_room = (body.new_room or "").strip() or None
        async with self.database.session() as db:
            db.add(row)
            db.add(AuditLog(actor_id=user.id, action="schedule.change", object_type="lesson", object_id=lesson.id[:64],
                            meta={"kind": body.kind, "group": body.group}))
            await db.commit()
            await db.refresh(row)
        self.overlay.put(row)
        return {"id": str(row.id), "kind": row.kind, "kind_label": KIND_LABELS[row.kind]}

    async def revert(self, user: User, change_id: uuid.UUID) -> None:
        async with self.database.session() as db:
            row = await db.get(LessonChange, change_id)
            if row is None:
                raise ApiError(404, "not_found", "Изменение не найдено.")
            from .academics.curriculum import SCHEDULE_OIDS

            code = next((code for code, oid in SCHEDULE_OIDS.items() if oid == row.group_oid), "")
            await self._group(user, code)
            await db.delete(row)
            db.add(AuditLog(actor_id=user.id, action="schedule.revert", object_type="lesson", object_id=row.lesson_id[:64]))
            await db.commit()
        self.overlay.drop(row.lesson_id)


async def seed_schedule_changes(database: Database, schedule, *, now: datetime | None = None) -> int:
    """Section 13.3: Anna has a moved lesson today, a room change; Boris a cancelled pair."""
    from .academics.curriculum import SCHEDULE_OIDS

    if schedule is None:
        return 0
    now = now or utcnow()
    async with database.session() as db:
        if await db.scalar(select(LessonChange.id).limit(1)):
            return 0
    day = now.astimezone(MOSCOW).date()
    while day.weekday() >= 5:
        day += timedelta(days=1)
    tomorrow = day + timedelta(days=1)
    while tomorrow.weekday() >= 5:
        tomorrow += timedelta(days=1)

    def lessons(code: str, when: date) -> list[Lesson]:
        return sorted(schedule.source.schedule(start=when, finish=when, group_oid=SCHEDULE_OIDS[code]), key=lambda x: x.starts_at)

    rows = []
    anna_today = lessons("ЭК-25-1", day)
    if anna_today:
        lesson = anna_today[-1]
        starts = lesson.starts_at + timedelta(hours=1, minutes=40)
        rows.append(LessonChange(lesson_id=lesson.id, group_oid=SCHEDULE_OIDS["ЭК-25-1"], kind="moved", title=lesson.title,
                                 was_starts_at=lesson.starts_at, was_ends_at=lesson.ends_at, was_room=lesson.room,
                                 new_starts_at=starts, new_ends_at=starts + (lesson.ends_at - lesson.starts_at),
                                 new_room="Б-205", note="Преподаватель на конференции до обеда", author_name="Демченко О. В."))
    anna_tomorrow = lessons("ЭК-25-1", tomorrow)
    if anna_tomorrow:
        lesson = anna_tomorrow[0]
        rows.append(LessonChange(lesson_id=lesson.id, group_oid=SCHEDULE_OIDS["ЭК-25-1"], kind="room", title=lesson.title,
                                 was_starts_at=lesson.starts_at, was_ends_at=lesson.ends_at, was_room=lesson.room,
                                 new_room="А-305", note="В аудитории ремонт проектора", author_name="Демченко О. В."))
    boris_tomorrow = lessons("ЭК-24-1", tomorrow)
    if boris_tomorrow:
        lesson = boris_tomorrow[-1]
        rows.append(LessonChange(lesson_id=lesson.id, group_oid=SCHEDULE_OIDS["ЭК-24-1"], kind="cancelled", title=lesson.title,
                                 was_starts_at=lesson.starts_at, was_ends_at=lesson.ends_at, was_room=lesson.room,
                                 note="Преподаватель заболел, отработка будет объявлена", author_name="Демченко О. В."))
    async with database.session() as db:
        for row in rows:
            db.add(row)
        await db.commit()
    return len(rows)


def register_schedule_change_routes(app: FastAPI, service: ScheduleChangeService) -> None:
    require_session = app.state.require_session

    @app.get("/api/staff/schedule/groups", tags=["staff"])
    async def groups(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.groups(current.user)}

    @app.get("/api/staff/schedule", tags=["staff"])
    async def week(group: str = Query(max_length=32), start: date = Query(), current: CurrentSession = Depends(require_session)) -> dict:
        return await service.week(current.user, group, start)

    @app.post("/api/staff/schedule/changes", status_code=201, tags=["staff"])
    async def change(body: ChangeBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.change(current.user, body)

    @app.delete("/api/staff/schedule/changes/{change_id}", status_code=204, tags=["staff"])
    async def revert(change_id: str, current: CurrentSession = Depends(require_session)) -> None:
        try:
            parsed = uuid.UUID(change_id)
        except ValueError:
            raise ApiError(404, "not_found", "Изменение не найдено.") from None
        await service.revert(current.user, parsed)
