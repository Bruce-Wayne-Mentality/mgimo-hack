"""K8: one feed of lessons, checkpoints, exams and request deadlines, plus an
.ics subscription by a personal read-only link.

The link token is access to personal data: only its SHA-256 is stored, it is
never logged, and the student can reissue it (the old link stops working).
"""

from __future__ import annotations

import asyncio
import hashlib
import secrets
import uuid
from collections.abc import Callable
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query, Request, Response
from sqlalchemy import ForeignKey, String, Uuid, select
from sqlalchemy.orm import Mapped, mapped_column

from .accounts.models import Student, User
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Base, Database, UTCDateTime, utcnow
from .ratelimit import RateLimiter

MOSCOW = ZoneInfo("Europe/Moscow")
KIND_LABELS = {"lesson": "Пара", "deadline": "Дедлайн", "exam": "Сессия", "request": "Заявка", "booking": "Бронь"}


class IcsToken(Base):
    __tablename__ = "ics_tokens"

    user_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class CalendarService:
    def __init__(self, database: Database, schedule, *, extra_sources: tuple = (),
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.schedule = schedule
        self.extra_sources = extra_sources  # async callables (db, student, start, finish) -> list[event]
        self.clock = clock

    async def events(self, student: Student, start: date, finish: date) -> list[dict]:
        from .academics.models import Checkpoint, Discipline, Grade
        from .student_requests.models import StudentRequest
        from .student_requests.service import OPEN_STATUSES

        events: list[dict] = []
        lessons = []
        chunk = start
        while chunk <= finish:  # the timetable source answers at most 31 days per call
            end = min(finish, chunk + timedelta(days=29))
            try:
                lessons += await asyncio.to_thread(self.schedule.get_schedule, student.email, chunk, end)
            except Exception:
                pass
            chunk = end + timedelta(days=1)
        for lesson in lessons:
            events.append({
                "id": f"lesson-{lesson.id}", "kind": "lesson", "title": lesson.title,
                "subtitle": lesson.kind, "starts_at": lesson.starts_at.isoformat(), "ends_at": lesson.ends_at.isoformat(),
                "all_day": False, "place": ", ".join(filter(None, [lesson.room, lesson.building])) or None, "link": "/schedule",
            })
        async with self.database.session() as db:
            disciplines = list((await db.scalars(select(Discipline).where(Discipline.group_id == student.group_id))).all())
            ids = [c.id for d in disciplines for c in d.checkpoints]
            graded = set((await db.scalars(
                select(Grade.checkpoint_id).where(Grade.student_id == student.id, Grade.checkpoint_id.in_(ids))
            )).all()) if ids else set()
            for discipline in disciplines:
                for checkpoint in discipline.checkpoints:
                    if checkpoint.is_final or checkpoint.due_on is None or not start <= checkpoint.due_on <= finish:
                        continue
                    starts = datetime.combine(checkpoint.due_on, time(23, 59), tzinfo=MOSCOW)
                    events.append({
                        "id": f"cp-{checkpoint.id}", "kind": "deadline", "title": f"{checkpoint.title}: {discipline.title}",
                        "subtitle": f"{checkpoint.weight} баллов" + (" · сдано" if checkpoint.id in graded else ""),
                        "starts_at": starts.isoformat(), "ends_at": starts.isoformat(), "all_day": True,
                        "done": checkpoint.id in graded, "place": None, "link": f"/study/{discipline.id}",
                    })
                if discipline.final_at and start <= discipline.final_at.astimezone(MOSCOW).date() <= finish:
                    events.append({
                        "id": f"final-{discipline.id}", "kind": "exam",
                        "title": f"{'Экзамен' if discipline.control_form == 'exam' else 'Зачёт'}: {discipline.title}",
                        "subtitle": discipline.teacher_name, "starts_at": discipline.final_at.isoformat(),
                        "ends_at": (discipline.final_at + timedelta(hours=3)).isoformat(), "all_day": False,
                        "place": discipline.final_room, "link": f"/study/{discipline.id}",
                    })
            requests = list((await db.scalars(
                select(StudentRequest).where(StudentRequest.student_id == student.id, StudentRequest.status.in_(OPEN_STATUSES))
            )).unique().all())
            for request in requests:
                due = request.due_at.astimezone(MOSCOW)
                if start <= due.date() <= finish:
                    events.append({
                        "id": f"req-{request.id}", "kind": "request", "title": f"Ориентир готовности: {request.type.title}",
                        "subtitle": request.number, "starts_at": request.due_at.isoformat(), "ends_at": request.due_at.isoformat(),
                        "all_day": False, "place": None, "link": f"/requests/{request.id}",
                    })
            for source in self.extra_sources:
                events.extend(await source(db, student, start, finish))
        events.sort(key=lambda e: (e["starts_at"], e["kind"] != "lesson"))
        return events

    async def link_status(self, user: User) -> dict:
        async with self.database.session() as db:
            row = await db.get(IcsToken, user.id)
        return {"active": row is not None, "created_at": row.created_at.isoformat() if row else None}

    async def reissue(self, user: User) -> str:
        token = secrets.token_urlsafe(32)
        async with self.database.session() as db:
            row = await db.get(IcsToken, user.id)
            if row is None:
                db.add(IcsToken(user_id=user.id, token_hash=_hash(token), created_at=self.clock()))
            else:
                row.token_hash = _hash(token)
                row.created_at = self.clock()
            await db.commit()
        return token

    async def revoke(self, user: User) -> None:
        async with self.database.session() as db:
            row = await db.get(IcsToken, user.id)
            if row is not None:
                await db.delete(row)
                await db.commit()

    async def student_by_token(self, token: str) -> Student | None:
        if not 20 <= len(token) <= 100:
            return None
        async with self.database.session() as db:
            row = await db.scalar(select(IcsToken).where(IcsToken.token_hash == _hash(token)))
            if row is None:
                return None
            student = await db.scalar(select(Student).where(Student.user_id == row.user_id))
            user = await db.get(User, row.user_id)
            if student is None or user is None or not user.is_active:
                return None
            return student


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\n", "\\n")


def _fold(line: str) -> str:
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line
    parts, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        if len(current) + len(encoded) > (75 if not parts else 74):
            parts.append(current.decode("utf-8"))
            current = b""
        current += encoded
    parts.append(current.decode("utf-8"))
    return "\r\n ".join(parts)


def to_ics(events: list[dict], now: datetime) -> str:
    def stamp(value: str) -> str:
        return datetime.fromisoformat(value).astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    lines = [
        "BEGIN:VCALENDAR", "VERSION:2.0", "PRODID:-//Tsifrovoy dekanat (concept)//RU", "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH", "X-WR-CALNAME:Цифровой деканат (демо)", "X-WR-TIMEZONE:Europe/Moscow",
        "REFRESH-INTERVAL;VALUE=DURATION:PT6H",
    ]
    for event in events:
        lines += ["BEGIN:VEVENT", f"UID:{event['id']}@dekanat.demo", f"DTSTAMP:{now.astimezone(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"]
        if event["all_day"]:
            day = datetime.fromisoformat(event["starts_at"]).astimezone(MOSCOW).date()
            lines += [f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}", f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}"]
        else:
            lines += [f"DTSTART:{stamp(event['starts_at'])}", f"DTEND:{stamp(event['ends_at'])}"]
        summary = event["title"] if event["kind"] == "lesson" else f"[{KIND_LABELS[event['kind']]}] {event['title']}"
        lines.append(f"SUMMARY:{_escape(summary)}")
        if event.get("subtitle"):
            lines.append(f"DESCRIPTION:{_escape(event['subtitle'] + ' · концепт, данные вымышленные')}")
        if event.get("place"):
            lines.append(f"LOCATION:{_escape(event['place'])}")
        if event["kind"] in ("deadline", "exam"):
            lines += ["BEGIN:VALARM", "ACTION:DISPLAY", f"DESCRIPTION:{_escape(summary)}",
                      "TRIGGER:-P1D" if event["kind"] == "exam" else "TRIGGER:-PT12H", "END:VALARM"]
        lines.append("END:VEVENT")
    lines.append("END:VCALENDAR")
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"


def register_calendar_routes(app: FastAPI, service: CalendarService) -> None:
    require_session = app.state.require_session
    feed_limit = RateLimiter(limit=30, window=60)

    def student_of(current: CurrentSession) -> Student:
        if current.user.role != "student" or current.user.student is None:
            raise ApiError(403, "forbidden", "Календарь доступен студентам.")
        return current.user.student

    @app.get("/api/calendar", tags=["calendar"])
    async def calendar(start: date, finish: date = Query(), current: CurrentSession = Depends(require_session)) -> dict:
        if finish < start or (finish - start).days > 62:
            raise ApiError(422, "validation_failed", "Период — не больше двух месяцев.")
        events = await service.events(student_of(current), start, finish)
        return {"start": start.isoformat(), "finish": finish.isoformat(), "events": events}

    @app.get("/api/calendar/ics", tags=["calendar"])
    async def ics_status(current: CurrentSession = Depends(require_session)) -> dict:
        student_of(current)
        return await service.link_status(current.user)

    @app.post("/api/calendar/ics", tags=["calendar"])
    async def ics_reissue(request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        student_of(current)
        token = await service.reissue(current.user)
        base = str(request.base_url).rstrip("/")
        return {"url": f"{base}/cal/{token}.ics", "webcal": f"webcal://{base.split('://', 1)[-1]}/cal/{token}.ics",
                **(await service.link_status(current.user))}

    @app.delete("/api/calendar/ics", status_code=204, tags=["calendar"])
    async def ics_revoke(current: CurrentSession = Depends(require_session)) -> None:
        student_of(current)
        await service.revoke(current.user)

    @app.get("/cal/{token}.ics", include_in_schema=False)
    async def ics_feed(token: str, request: Request) -> Response:
        feed_limit.check(request, "ics")
        student = await service.student_by_token(token)
        if student is None:
            return Response("Not found", status_code=404, media_type="text/plain")
        today = service.clock().astimezone(MOSCOW).date()
        events = await service.events(student, today - timedelta(days=14), today + timedelta(days=62))
        return Response(to_ics(events, service.clock()), media_type="text/calendar; charset=utf-8",
                        headers={"Cache-Control": "private, no-store", "Content-Disposition": "inline; filename=\"dekanat.ics\""})
