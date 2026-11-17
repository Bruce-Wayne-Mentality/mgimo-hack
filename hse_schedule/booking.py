"""K6: booking classrooms, coworking spaces and consultation hours; K12 heat map.

- Free slots = opening hours − active bookings − timetable lessons in the room.
  Grid 30 min, a booking lasts 30 min … 3 h.
- Student limits (concept assumptions): ≤ 3 active future bookings,
  ≤ 4 h per day, not further than 14 days ahead.
- Correctness under concurrent requests is guaranteed by PostgreSQL:
  EXCLUDE USING gist (resource_id WITH =, tstzrange(starts_at, ends_at) WITH &&)
  WHERE status = 'active'. The code check only gives a friendly message.
- «Я на месте» works from 10 min before to 15 min after the start; a booking
  without check-in is released automatically after that.
- Times are stored in UTC and shown in Europe/Moscow.
"""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, Uuid, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .accounts.models import AuditLog, Student, User
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Base, Database, JSONType, UTCDateTime, utcnow, uuid7

MOSCOW = ZoneInfo("Europe/Moscow")
STEP = 30
MIN_MINUTES, MAX_MINUTES = 30, 180
MAX_ACTIVE, MAX_DAY_MINUTES, MAX_DAYS_AHEAD = 3, 240, 14
CHECKIN_BEFORE, CHECKIN_AFTER = timedelta(minutes=10), timedelta(minutes=15)
KIND_LABELS = {"classroom": "Аудитория", "coworking": "Коворкинг", "consultation": "Консультация"}
STATUS_LABELS = {"active": "Активна", "cancelled": "Отменена", "released": "Освобождена", "done": "Завершена"}
FEATURE_LABELS = {"projector": "проектор", "sockets": "розетки", "whiteboard": "доска", "computers": "компьютеры", "screen": "экран", "quiet": "тишина"}


class Resource(Base):
    __tablename__ = "resources"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(16))
    building: Mapped[str] = mapped_column(String(64))
    floor: Mapped[int] = mapped_column(Integer)
    capacity: Mapped[int] = mapped_column(Integer)
    features: Mapped[list] = mapped_column(JSONType, default=list)
    room: Mapped[str | None] = mapped_column(String(32), nullable=True)  # timetable auditorium, if any
    opens: Mapped[str] = mapped_column(String(5), default="08:00")
    closes: Mapped[str] = mapped_column(String(5), default="22:00")
    host: Mapped[str | None] = mapped_column(String(200), nullable=True)
    is_bookable: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint("kind IN ('classroom', 'coworking', 'consultation')", name="kind_known"),)


class Booking(Base):
    __tablename__ = "bookings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    resource_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("resources.id", ondelete="CASCADE"))
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    starts_at: Mapped[datetime] = mapped_column(UTCDateTime)
    ends_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(16), default="active")
    purpose: Mapped[str | None] = mapped_column(String(200), nullable=True)
    checked_in_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    resource: Mapped[Resource] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("status IN ('active', 'cancelled', 'released', 'done')", name="status_known"),
        CheckConstraint("ends_at > starts_at", name="positive_duration"),
        Index("ix_bookings_resource_start", "resource_id", "starts_at"),
    )


class BookBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resource_id: StrictStr
    starts_at: datetime
    minutes: int = Field(ge=MIN_MINUTES, le=MAX_MINUTES)
    purpose: StrictStr | None = Field(default=None, max_length=200)


class CancelBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: StrictStr = Field(min_length=3, max_length=500)


def _hm(value: str) -> time:
    hours, minutes = value.split(":")
    return time(int(hours), int(minutes))


def _local(day: date, moment: time) -> datetime:
    return datetime.combine(day, moment, tzinfo=MOSCOW)


def _uuid(value: str, message: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ApiError(404, "not_found", message) from None


class BookingService:
    def __init__(self, database: Database, schedule=None, *, notify: Callable[[str, list[dict]], None] | None = None,
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.schedule = schedule
        self.notify = notify
        self.clock = clock
        # One writer per resource inside this process (SQLite has no exclusion
        # constraints); across processes PostgreSQL's EXCLUDE is the guarantee.
        self._locks: dict[uuid.UUID, asyncio.Lock] = {}

    # ---- timetable occupancy -------------------------------------------------

    def _lessons_in(self, room: str, day: date) -> list[tuple[datetime, datetime]]:
        source = getattr(self.schedule, "source", None)
        if source is None:
            return []
        from .academics.curriculum import SCHEDULE_OIDS

        busy = []
        for oid in SCHEDULE_OIDS.values():
            try:
                lessons = source.schedule(start=day, finish=day, group_oid=oid)
            except Exception:
                continue
            busy += [(lesson.starts_at, lesson.ends_at) for lesson in lessons if lesson.room == room]
        return busy

    async def _release_no_shows(self, db) -> None:
        """Bookings nobody checked in to are freed 15 minutes after the start."""
        now = self.clock()
        rows = (await db.scalars(select(Booking).where(
            Booking.status == "active", Booking.checked_in_at.is_(None), Booking.starts_at < now - CHECKIN_AFTER
        ))).all()
        for row in rows:
            row.status = "released"
        done = (await db.scalars(select(Booking).where(Booking.status == "active", Booking.ends_at < now))).all()
        for row in done:
            row.status = "done"
        if rows or done:
            await db.commit()

    async def _busy(self, db, resource: Resource, day: date) -> list[tuple[datetime, datetime, str]]:
        start, finish = _local(day, time(0)), _local(day + timedelta(days=1), time(0))
        rows = (await db.scalars(select(Booking).where(
            Booking.resource_id == resource.id, Booking.status == "active",
            Booking.starts_at < finish, Booking.ends_at > start,
        ))).all()
        busy = [(row.starts_at, row.ends_at, "booking") for row in rows]
        if resource.room:
            lessons = await asyncio.to_thread(self._lessons_in, resource.room, day)
            busy += [(s, e, "lesson") for s, e in lessons]
        return busy

    def _slots(self, resource: Resource, day: date, busy) -> list[dict]:
        now = self.clock()
        slots = []
        moment = _local(day, _hm(resource.opens))
        close = _local(day, _hm(resource.closes))
        while moment + timedelta(minutes=STEP) <= close:
            end = moment + timedelta(minutes=STEP)
            reason = next((kind for s, e, kind in busy if s < end and e > moment), None)
            if moment < now:
                reason = reason or "past"
            slots.append({"starts_at": moment.isoformat(), "free": reason is None, "reason": reason})
            moment = end
        return slots

    def resource_payload(self, resource: Resource) -> dict:
        return {
            "id": str(resource.id), "code": resource.code, "title": resource.title, "kind": resource.kind,
            "kind_label": KIND_LABELS[resource.kind], "building": resource.building, "floor": resource.floor,
            "capacity": resource.capacity, "features": [FEATURE_LABELS.get(f, f) for f in resource.features],
            "opens": resource.opens, "closes": resource.closes, "host": resource.host,
        }

    async def resources(self, day: date, kind: str | None) -> list[dict]:
        async with self.database.session() as db:
            await self._release_no_shows(db)
            query = select(Resource).where(Resource.is_bookable.is_(True)).order_by(Resource.kind, Resource.title)
            if kind:
                query = query.where(Resource.kind == kind)
            items = []
            for resource in (await db.scalars(query)).all():
                slots = self._slots(resource, day, await self._busy(db, resource, day))
                items.append({**self.resource_payload(resource), "slots": slots,
                              "free_count": sum(1 for slot in slots if slot["free"])})
        return items

    def booking_payload(self, row: Booking, *, owner: str | None = None) -> dict:
        now = self.clock()
        return {
            "id": str(row.id), "resource": self.resource_payload(row.resource), "starts_at": row.starts_at.isoformat(),
            "ends_at": row.ends_at.isoformat(), "status": row.status, "status_label": STATUS_LABELS[row.status],
            "purpose": row.purpose, "checked_in": row.checked_in_at is not None, "cancel_reason": row.cancel_reason,
            "can_check_in": row.status == "active" and row.checked_in_at is None
            and row.starts_at - CHECKIN_BEFORE <= now <= row.starts_at + CHECKIN_AFTER,
            "can_cancel": row.status == "active" and now < row.starts_at,
            "owner": owner,
        }

    async def book(self, user: User, body: BookBody) -> dict:
        if user.role != "student" or user.student is None:
            raise ApiError(403, "forbidden", "Бронируют студенты.")
        now = self.clock()
        starts = body.starts_at if body.starts_at.tzinfo else body.starts_at.replace(tzinfo=MOSCOW)
        starts = starts.astimezone(timezone.utc)
        ends = starts + timedelta(minutes=body.minutes)
        local = starts.astimezone(MOSCOW)
        if body.minutes % STEP or local.minute % STEP or local.second:
            raise ApiError(422, "validation_failed", "Бронь начинается и заканчивается по сетке 30 минут.")
        if starts < now:
            raise ApiError(422, "validation_failed", "Это время уже прошло.")
        if local.date() > (now.astimezone(MOSCOW).date() + timedelta(days=MAX_DAYS_AHEAD)):
            raise ApiError(422, "validation_failed", f"Бронировать можно не дальше чем на {MAX_DAYS_AHEAD} дней вперёд.")
        resource_id = _uuid(body.resource_id, "Помещение не найдено.")
        async with self._locks.setdefault(resource_id, asyncio.Lock()):
            return await self._book(user, body, resource_id, starts, ends, local, now)

    async def _book(self, user: User, body: BookBody, resource_id: uuid.UUID, starts: datetime, ends: datetime,
                    local: datetime, now: datetime) -> dict:
        async with self.database.session() as db:
            await self._release_no_shows(db)
            resource = await db.get(Resource, resource_id)
            if resource is None or not resource.is_bookable:
                raise ApiError(404, "not_found", "Помещение не найдено.")
            if local.time() < _hm(resource.opens) or ends.astimezone(MOSCOW).time() > _hm(resource.closes) \
                    or ends.astimezone(MOSCOW).date() != local.date():
                raise ApiError(422, "validation_failed", f"Помещение работает с {resource.opens} до {resource.closes}.")
            mine = (await db.scalars(select(Booking).where(
                Booking.user_id == user.id, Booking.status == "active", Booking.ends_at > now))).all()
            if len(mine) >= MAX_ACTIVE:
                raise ApiError(409, "limit", f"Не больше {MAX_ACTIVE} активных броней. Отмените ненужную.")
            same_day = sum((b.ends_at - b.starts_at).total_seconds() / 60 for b in mine
                           if b.starts_at.astimezone(MOSCOW).date() == local.date())
            if same_day + body.minutes > MAX_DAY_MINUTES:
                raise ApiError(409, "limit", "Не больше 4 часов брони в день.")
            for s, e, kind in await self._busy(db, resource, local.date()):
                if s < ends and e > starts:
                    raise ApiError(409, "conflict", "В это время занято парой." if kind == "lesson"
                                   else "Это время только что заняли. Выберите другое.")
            row = Booking(resource_id=resource.id, user_id=user.id, starts_at=starts, ends_at=ends, status="active",
                          purpose=(body.purpose or "").strip() or None, created_at=now)
            db.add(row)
            db.add(AuditLog(actor_id=user.id, action="booking.create", object_type="booking", object_id=str(row.id)))
            try:
                await db.commit()
            except IntegrityError:
                # Two requests raced for the same time: the database constraint picked one.
                await db.rollback()
                raise ApiError(409, "conflict", "Это время только что заняли. Выберите другое.") from None
            await db.refresh(row)
            return self.booking_payload(row)

    async def mine(self, user: User) -> list[dict]:
        async with self.database.session() as db:
            await self._release_no_shows(db)
            rows = (await db.scalars(select(Booking).where(Booking.user_id == user.id)
                                     .order_by(Booking.starts_at.desc()).limit(30))).all()
        now = self.clock()
        upcoming = sorted((r for r in rows if r.status == "active" and r.ends_at > now), key=lambda r: r.starts_at)
        past = [r for r in rows if r not in upcoming]
        return [self.booking_payload(r) for r in (*upcoming, *past)]

    async def _own(self, db, user: User, booking_id: uuid.UUID) -> Booking:
        row = await db.get(Booking, booking_id)
        if row is None or row.user_id != user.id:
            raise ApiError(404, "not_found", "Бронь не найдена.")
        return row

    async def cancel(self, user: User, booking_id: uuid.UUID) -> dict:
        async with self.database.session() as db:
            row = await self._own(db, user, booking_id)
            if row.status != "active" or self.clock() >= row.starts_at:
                raise ApiError(409, "not_possible", "Отменить можно только будущую активную бронь.")
            row.status = "cancelled"
            row.cancel_reason = "Отменена студентом"
            await db.commit()
            return self.booking_payload(row)

    async def check_in(self, user: User, booking_id: uuid.UUID) -> dict:
        async with self.database.session() as db:
            await self._release_no_shows(db)
            row = await self._own(db, user, booking_id)
            now = self.clock()
            if row.status != "active" or not row.starts_at - CHECKIN_BEFORE <= now <= row.starts_at + CHECKIN_AFTER:
                raise ApiError(409, "not_possible", "Отметиться можно за 10 минут до начала и в течение 15 минут после.")
            row.checked_in_at = now
            await db.commit()
            return self.booking_payload(row)

    # ---- staff --------------------------------------------------------------

    async def staff_day(self, user: User, day: date) -> list[dict]:
        if user.role not in ("staff", "admin"):
            raise ApiError(403, "forbidden", "Раздел для сотрудников.")
        start, finish = _local(day, time(0)), _local(day + timedelta(days=1), time(0))
        async with self.database.session() as db:
            await self._release_no_shows(db)
            rows = (await db.execute(
                select(Booking, Student.full_name).join(Student, Student.user_id == Booking.user_id, isouter=True)
                .where(Booking.starts_at < finish, Booking.ends_at > start).order_by(Booking.starts_at)
            )).all()
        return [self.booking_payload(row, owner=name) for row, name in rows]

    async def staff_cancel(self, user: User, booking_id: uuid.UUID, reason: str) -> dict:
        if user.role not in ("staff", "admin"):
            raise ApiError(404, "not_found", "Бронь не найдена.")
        async with self.database.session() as db:
            row = await db.get(Booking, booking_id)
            if row is None or row.status != "active":
                raise ApiError(404, "not_found", "Активная бронь не найдена.")
            row.status = "cancelled"
            row.cancel_reason = reason.strip()
            db.add(AuditLog(actor_id=user.id, action="booking.cancel", object_type="booking", object_id=str(row.id)))
            email = await db.scalar(select(Student.email).where(Student.user_id == row.user_id))
            await db.commit()
            payload = self.booking_payload(row)
        if email and self.notify:
            try:
                local = row.starts_at.astimezone(MOSCOW).strftime("%d.%m в %H:%M")
                self.notify(email, [{"event_key": f"booking:{row.id}:cancelled", "kind": "booking",
                                     "title": f"Бронь отменена: {row.resource.title}",
                                     "body": f"{local}. Причина: {row.cancel_reason}", "payload": {"link": "/booking"}}])
            except Exception:
                pass
        return payload

    # ---- K12 heat map -------------------------------------------------------

    async def heatmap(self, day: date) -> dict:
        """Share of each hour that is taken by bookings or lessons (not real presence)."""
        hours = list(range(8, 22))
        async with self.database.session() as db:
            rows = []
            for resource in (await db.scalars(select(Resource).order_by(Resource.kind, Resource.title))).all():
                busy = await self._busy(db, resource, day)
                cells = []
                for hour in hours:
                    start, end = _local(day, time(hour)), _local(day, time(hour)) + timedelta(hours=1)
                    taken = sum(max(0, (min(e, end) - max(s, start)).total_seconds()) for s, e, _ in busy)
                    cells.append(round(min(1.0, taken / 3600), 2))
                rows.append({"resource": self.resource_payload(resource), "cells": cells})
        return {"date": day.isoformat(), "hours": hours, "rows": rows}

    # ---- integration --------------------------------------------------------

    async def calendar_events(self, db, student: Student, start: date, finish: date) -> list[dict]:
        rows = (await db.scalars(select(Booking).where(
            Booking.user_id == student.user_id, Booking.status == "active",
            Booking.starts_at >= _local(start, time(0)), Booking.starts_at < _local(finish + timedelta(days=1), time(0)),
        ))).all()
        return [{
            "id": f"booking-{row.id}", "kind": "booking", "title": f"Бронь: {row.resource.title}",
            "subtitle": row.purpose, "starts_at": row.starts_at.isoformat(), "ends_at": row.ends_at.isoformat(),
            "all_day": False, "place": f"{row.resource.building}, {row.resource.floor} этаж", "link": "/booking",
        } for row in rows]


RESOURCES = [
    {"code": "B-118", "title": "Компьютерный класс Б-118", "kind": "classroom", "building": "Корпус Б", "floor": 1, "capacity": 24,
     "features": ["computers", "projector", "whiteboard"], "room": "Б-118"},
    {"code": "A-210", "title": "Аудитория А-210", "kind": "classroom", "building": "Корпус А", "floor": 2, "capacity": 40,
     "features": ["projector", "whiteboard"], "room": "А-210"},
    {"code": "V-212", "title": "Аудитория В-212", "kind": "classroom", "building": "Корпус В", "floor": 2, "capacity": 30,
     "features": ["whiteboard", "sockets"], "room": "В-212"},
    {"code": "COWORK-ATRIUM", "title": "Коворкинг «Атриум»", "kind": "coworking", "building": "Корпус А", "floor": 1, "capacity": 12,
     "features": ["sockets", "whiteboard"]},
    {"code": "MEET-214", "title": "Переговорная 2.14", "kind": "coworking", "building": "Корпус Б", "floor": 2, "capacity": 6,
     "features": ["screen", "sockets"]},
    {"code": "QUIET-LIB", "title": "Тихая комната библиотеки", "kind": "coworking", "building": "Корпус В", "floor": 3, "capacity": 4,
     "features": ["quiet", "sockets"], "opens": "09:00", "closes": "21:00"},
    {"code": "CONSULT-DEAN", "title": "Приём в деканате", "kind": "consultation", "building": "Корпус А", "floor": 1, "capacity": 1,
     "features": [], "opens": "14:00", "closes": "17:00", "host": "Демченко О. В., специалист деканата"},
    {"code": "CONSULT-MATH", "title": "Консультация по математике", "kind": "consultation", "building": "Корпус В", "floor": 1, "capacity": 1,
     "features": [], "opens": "16:00", "closes": "18:00", "host": "Соколовский В. А., матанализ"},
]


async def seed_booking(database: Database, *, now: datetime | None = None) -> int:
    now = now or utcnow()
    async with database.session() as db:
        if await db.scalar(select(func.count()).select_from(Resource)):
            return 0
        resources = {}
        for data in RESOURCES:
            resources[data["code"]] = Resource(**data)
            db.add(resources[data["code"]])
        await db.flush()
        users = {u.login: u for u in (await db.scalars(select(User).where(
            User.login.in_(["student.anna", "student.boris"])))).all()}
        tomorrow = now.astimezone(MOSCOW).date() + timedelta(days=1)
        while tomorrow.weekday() >= 5:
            tomorrow += timedelta(days=1)
        if "student.anna" in users:
            db.add(Booking(resource_id=resources["MEET-214"].id, user_id=users["student.anna"].id,
                           starts_at=_local(tomorrow, time(14, 30)), ends_at=_local(tomorrow, time(16, 0)),
                           status="active", purpose="Подготовка проекта по эконометрике", created_at=now))
        if "student.boris" in users:
            db.add(Booking(resource_id=resources["COWORK-ATRIUM"].id, user_id=users["student.boris"].id,
                           starts_at=_local(tomorrow, time(15, 0)), ends_at=_local(tomorrow, time(17, 0)),
                           status="active", purpose="Курсовая работа", created_at=now))
        await db.commit()
        return len(RESOURCES)


def register_booking_routes(app: FastAPI, service: BookingService) -> None:
    require_session = app.state.require_session

    def check_day(day: date | None) -> date:
        today = service.clock().astimezone(MOSCOW).date()
        day = day or today
        if not today - timedelta(days=1) <= day <= today + timedelta(days=MAX_DAYS_AHEAD):
            raise ApiError(422, "validation_failed", "Дата — от сегодня до двух недель вперёд.")
        return day

    @app.get("/api/resources", tags=["booking"])
    async def resources(day: date | None = Query(default=None, alias="date"),
                        kind: Literal["classroom", "coworking", "consultation"] | None = None,
                        current: CurrentSession = Depends(require_session)) -> dict:
        return {"date": check_day(day).isoformat(), "items": await service.resources(check_day(day), kind),
                "limits": {"active": MAX_ACTIVE, "day_minutes": MAX_DAY_MINUTES, "days_ahead": MAX_DAYS_AHEAD}}

    @app.get("/api/resources/heatmap", tags=["booking"])
    async def heatmap(day: date | None = Query(default=None, alias="date"), current: CurrentSession = Depends(require_session)) -> dict:
        return await service.heatmap(check_day(day))

    @app.get("/api/bookings", tags=["booking"])
    async def mine(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.mine(current.user)}

    @app.post("/api/bookings", status_code=201, tags=["booking"])
    async def book(body: BookBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.book(current.user, body)

    @app.post("/api/bookings/{booking_id}/cancel", tags=["booking"])
    async def cancel(booking_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.cancel(current.user, _uuid(booking_id, "Бронь не найдена."))

    @app.post("/api/bookings/{booking_id}/check-in", tags=["booking"])
    async def check_in(booking_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.check_in(current.user, _uuid(booking_id, "Бронь не найдена."))

    @app.get("/api/staff/bookings", tags=["staff"])
    async def staff_day(day: date | None = Query(default=None, alias="date"), current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.staff_day(current.user, check_day(day))}

    @app.post("/api/staff/bookings/{booking_id}/cancel", tags=["staff"])
    async def staff_cancel(booking_id: str, body: CancelBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.staff_cancel(current.user, _uuid(booking_id, "Бронь не найдена."), body.reason)
