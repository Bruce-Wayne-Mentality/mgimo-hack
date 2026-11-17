"""K7 «Красная кнопка»: a complaint about unfairness that the administrator
must answer with a reasoned response within the SLA.

Modes:
- open: the author is visible to the administrator;
- confidential: the author is stored but hidden; revealing it is a separate,
  audited action of the ombudsman (admin) with a reason;
- anonymous: the author is not stored at all; the student gets a one-time
  tracking code and the database keeps only its SHA-256.
No IP address or User-Agent is written for this module.
"""

from __future__ import annotations

import hashlib
import secrets
import uuid
from collections.abc import Callable
from datetime import date, datetime
from typing import Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict, Field, StrictStr
from sqlalchemy import CheckConstraint, Date, ForeignKey, Integer, String, Text, Uuid, func, select
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .accounts.models import AuditLog, Student, User
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Base, Database, UTCDateTime, utcnow, uuid7
from .ratelimit import RateLimiter
from .student_requests.service import MOSCOW, add_business_days

CATEGORIES = {
    "grade": "Спорная оценка",
    "pressure": "Давление или некорректное поведение",
    "regulation": "Нарушение регламента",
    "demand": "Неправомерное требование",
    "other": "Другое",
}
MODES = {"open": "Открыто", "confidential": "Конфиденциально", "anonymous": "Анонимно"}
STATUS_LABELS = {
    "new": "Подано", "accepted": "Принято к рассмотрению", "investigating": "Идёт проверка",
    "resolved": "Решено", "rejected": "Отклонено", "escalated": "Передано выше",
}
OPEN = ("new", "accepted", "investigating", "escalated")
TRANSITIONS: dict[tuple[str, str], bool] = {  # (from, to) -> note required
    ("new", "accepted"): False,
    ("new", "rejected"): True,
    ("accepted", "investigating"): False,
    ("accepted", "resolved"): True,
    ("investigating", "resolved"): True,
    ("investigating", "rejected"): True,
    ("new", "escalated"): True,
    ("accepted", "escalated"): True,
    ("investigating", "escalated"): True,
    ("escalated", "investigating"): False,
    ("escalated", "resolved"): True,
}
FIRST_RESPONSE_DAYS = 3
RESOLVE_DAYS = 10
DAILY_LIMIT = 3


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    category: Mapped[str] = mapped_column(String(16))
    summary: Mapped[str] = mapped_column(Text)
    happened_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    context: Mapped[str | None] = mapped_column(Text, nullable=True)
    mode: Mapped[str] = mapped_column(String(16))
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    track_hash: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="new")
    response: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    first_response_due: Mapped[datetime] = mapped_column(UTCDateTime)
    resolve_due: Mapped[datetime] = mapped_column(UTCDateTime)
    responded_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    events: Mapped[list[ComplaintEvent]] = relationship(order_by="ComplaintEvent.at", lazy="selectin", cascade="all, delete-orphan")

    __table_args__ = (
        CheckConstraint("mode IN ('open', 'confidential', 'anonymous')", name="mode_known"),
        CheckConstraint("status IN ('new', 'accepted', 'investigating', 'resolved', 'rejected', 'escalated')", name="status_known"),
        CheckConstraint("mode <> 'anonymous' OR author_id IS NULL", name="anonymous_has_no_author"),
    )


class ComplaintEvent(Base):
    __tablename__ = "complaint_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16))
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ComplaintCounter(Base):
    __tablename__ = "complaint_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    value: Mapped[int] = mapped_column(Integer, default=0)


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    category: Literal["grade", "pressure", "regulation", "demand", "other"]
    summary: StrictStr = Field(min_length=30, max_length=4000)
    happened_on: date | None = None
    context: StrictStr | None = Field(default=None, max_length=2000)
    mode: Literal["open", "confidential", "anonymous"]


class TrackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    code: StrictStr = Field(min_length=6, max_length=40)


class TransitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: Literal["accepted", "investigating", "resolved", "rejected", "escalated"]
    note: StrictStr | None = Field(default=None, max_length=4000)


class RevealBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: StrictStr = Field(min_length=10, max_length=500)


def _hash(code: str) -> str:
    return hashlib.sha256(code.strip().upper().encode("utf-8")).hexdigest()


def tracking_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    raw = "".join(secrets.choice(alphabet) for _ in range(12))
    return f"RB-{raw[:4]}-{raw[4:8]}-{raw[8:]}"


class ComplaintService:
    def __init__(self, database: Database, *, notify: Callable[[str, list[dict]], None] | None = None,
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.notify = notify
        self.clock = clock

    def payload(self, row: Complaint, *, admin: bool = False, author: str | None = None) -> dict:
        now = self.clock()
        overdue_first = row.status == "new" and now > row.first_response_due
        overdue = row.status in OPEN and now > row.resolve_due
        data = {
            "id": str(row.id), "number": row.number, "category": row.category, "category_label": CATEGORIES[row.category],
            "summary": row.summary, "happened_on": row.happened_on.isoformat() if row.happened_on else None,
            "context": row.context, "mode": row.mode, "mode_label": MODES[row.mode],
            "status": row.status, "status_label": STATUS_LABELS[row.status], "response": row.response,
            "created_at": row.created_at.isoformat(), "first_response_due": row.first_response_due.isoformat(),
            "resolve_due": row.resolve_due.isoformat(), "closed_at": row.closed_at.isoformat() if row.closed_at else None,
            "overdue": overdue or overdue_first,
            "events": [{"to": e.to_status, "label": STATUS_LABELS[e.to_status], "note": e.note, "at": e.at.isoformat()} for e in row.events],
        }
        if admin:
            data["author"] = author
            data["actions"] = [
                {"to": to, "label": STATUS_LABELS[to], "note_required": need}
                for (origin, to), need in TRANSITIONS.items() if origin == row.status
            ]
        return data

    async def create(self, user: User, body: CreateBody) -> tuple[Complaint, str | None]:
        if user.role != "student" or user.student is None:
            raise ApiError(403, "forbidden", "Обращение подают студенты.")
        now = self.clock()
        async with self.database.session() as db:
            if body.mode != "anonymous":
                start = now.astimezone(MOSCOW).replace(hour=0, minute=0, second=0, microsecond=0)
                count = await db.scalar(select(func.count()).select_from(Complaint).where(
                    Complaint.author_id == user.id, Complaint.created_at >= start))
                if count >= DAILY_LIMIT:
                    raise ApiError(429, "rate_limited", "Не больше трёх обращений в сутки.")
            year = now.astimezone(MOSCOW).year
            counter = await db.scalar(select(ComplaintCounter).where(ComplaintCounter.year == year).with_for_update())
            if counter is None:
                counter = ComplaintCounter(year=year, value=0)
                db.add(counter)
            counter.value += 1
            code = tracking_code()
            row = Complaint(
                number=f"КК-{year}-{counter.value:04d}", category=body.category, summary=body.summary.strip(),
                happened_on=body.happened_on, context=(body.context or "").strip() or None, mode=body.mode,
                author_id=None if body.mode == "anonymous" else user.id,
                track_hash=_hash(code) if body.mode == "anonymous" else None, status="new", created_at=now,
                first_response_due=add_business_days(now, FIRST_RESPONSE_DAYS),
                resolve_due=add_business_days(now, RESOLVE_DAYS),
            )
            row.events.append(ComplaintEvent(from_status=None, to_status="new", at=now))
            db.add(row)
            # Anonymous: the audit row carries no actor, so nothing links the account to it.
            db.add(AuditLog(actor_id=None if body.mode == "anonymous" else user.id, action="complaint.create",
                            object_type="complaint", object_id=str(row.id), meta={"mode": body.mode}))
            await db.commit()
            return row, code if body.mode == "anonymous" else None

    async def own(self, user: User) -> list[Complaint]:
        async with self.database.session() as db:
            return list((await db.scalars(
                select(Complaint).where(Complaint.author_id == user.id).order_by(Complaint.created_at.desc())
            )).all())

    async def get_own(self, user: User, complaint_id: uuid.UUID) -> Complaint:
        async with self.database.session() as db:
            row = await db.get(Complaint, complaint_id)
        if row is None or row.author_id != user.id:
            raise ApiError(404, "not_found", "Обращение не найдено.")
        return row

    async def track(self, code: str) -> Complaint | None:
        async with self.database.session() as db:
            return await db.scalar(select(Complaint).where(Complaint.track_hash == _hash(code)))

    # ---- administrator ---------------------------------------------------

    @staticmethod
    def _admin(user: User) -> None:
        if not user.is_active or user.role != "admin":
            raise ApiError(404, "not_found", "Обращение не найдено.")

    async def queue(self, user: User) -> list[dict]:
        self._admin(user)
        async with self.database.session() as db:
            rows = list((await db.scalars(select(Complaint).order_by(Complaint.created_at.desc()))).all())
            names = await self._names(db, [r.author_id for r in rows if r.mode == "open" and r.author_id])
        items = [self.payload(r, admin=True, author=self._author_label(r, names)) for r in rows]
        items.sort(key=lambda item: (item["status"] not in OPEN, not item["overdue"], item["resolve_due"]))
        return items

    async def _names(self, db, ids) -> dict:
        if not ids:
            return {}
        rows = await db.execute(select(Student.user_id, Student.full_name, Student.group_id).where(Student.user_id.in_(ids)))
        return {user_id: name for user_id, name, _ in rows.all()}

    @staticmethod
    def _author_label(row: Complaint, names: dict) -> str:
        if row.mode == "anonymous":
            return "Аноним (автор не хранится)"
        if row.mode == "confidential":
            return "Скрыт (конфиденциально)"
        return names.get(row.author_id, "Студент")

    async def admin_get(self, user: User, complaint_id: uuid.UUID) -> dict:
        self._admin(user)
        async with self.database.session() as db:
            row = await db.get(Complaint, complaint_id)
            if row is None:
                raise ApiError(404, "not_found", "Обращение не найдено.")
            names = await self._names(db, [row.author_id] if row.mode == "open" and row.author_id else [])
        return self.payload(row, admin=True, author=self._author_label(row, names))

    async def reveal(self, user: User, complaint_id: uuid.UUID, reason: str) -> dict:
        self._admin(user)
        async with self.database.session() as db:
            row = await db.get(Complaint, complaint_id)
            if row is None or row.mode != "confidential" or row.author_id is None:
                raise ApiError(409, "not_possible", "Автора можно раскрыть только у конфиденциального обращения.")
            names = await self._names(db, [row.author_id])
            db.add(AuditLog(actor_id=user.id, action="complaint.reveal_author", object_type="complaint",
                            object_id=str(row.id), meta={"reason": reason}))
            await db.commit()
        data = self.payload(row, admin=True, author=names.get(row.author_id, "Студент"))
        data["revealed"] = True
        return data

    async def transition(self, user: User, complaint_id: uuid.UUID, to: str, note: str | None) -> dict:
        self._admin(user)
        note = (note or "").strip() or None
        now = self.clock()
        async with self.database.session() as db:
            row = await db.get(Complaint, complaint_id)
            if row is None:
                raise ApiError(404, "not_found", "Обращение не найдено.")
            rule = TRANSITIONS.get((row.status, to))
            if rule is None:
                raise ApiError(409, "invalid_transition", f"Из статуса «{STATUS_LABELS[row.status]}» так перейти нельзя.")
            if rule and not note:
                raise ApiError(422, "validation_failed", "Нужен мотивированный ответ.", fields={"note": "Напишите ответ."})
            origin = row.status
            row.status = to
            if row.responded_at is None:
                row.responded_at = now
            if note and to in ("resolved", "rejected"):
                row.response = note
            if to in ("resolved", "rejected"):
                row.closed_at = now
            row.events.append(ComplaintEvent(from_status=origin, to_status=to, note=note, at=now))
            db.add(AuditLog(actor_id=user.id, action="complaint.transition", object_type="complaint", object_id=str(row.id),
                            meta={"from": origin, "to": to}))
            email = None
            if row.author_id:
                email = await db.scalar(select(Student.email).where(Student.user_id == row.author_id))
            await db.commit()
            names = await self._names(db, [row.author_id] if row.mode == "open" and row.author_id else [])
        if email and self.notify:
            try:
                self.notify(email, [{
                    "event_key": f"complaint:{row.id}:{to}:{now.timestamp()}", "kind": "complaint",
                    "title": f"Обращение {row.number}: {STATUS_LABELS[to]}", "body": (note or "")[:300],
                    "payload": {"link": f"/complaints/{row.id}"},
                }])
            except Exception:
                pass
        return self.payload(row, admin=True, author=self._author_label(row, names))


DEMO_TRACKING_CODE = "RB-DEMO-2026-TRACK"


async def seed_complaints(database: Database, *, now: datetime | None = None) -> int:
    from datetime import timedelta

    now = now or utcnow()
    async with database.session() as db:
        if await db.scalar(select(func.count()).select_from(Complaint)):
            return 0
        boris = await db.scalar(select(User).where(User.login == "student.boris"))
        year = now.astimezone(MOSCOW).year
        counter = ComplaintCounter(year=year, value=0)
        db.add(counter)

        def make(**values) -> Complaint:
            counter.value += 1
            created = values.pop("created_at")
            steps = values.pop("steps", [])
            row = Complaint(number=f"КК-{year}-{counter.value:04d}", created_at=created,
                            first_response_due=add_business_days(created, FIRST_RESPONSE_DAYS),
                            resolve_due=add_business_days(created, RESOLVE_DAYS), status="new", **values)
            row.events.append(ComplaintEvent(from_status=None, to_status="new", at=created))
            status = "new"
            for to, offset, note in steps:
                row.events.append(ComplaintEvent(from_status=status, to_status=to, note=note, at=created + offset))
                status = to
                row.responded_at = row.responded_at or created + offset
                if to in ("resolved", "rejected"):
                    row.response = note
                    row.closed_at = created + offset
            row.status = status
            db.add(row)
            return row

        make(category="regulation", mode="anonymous", track_hash=_hash(DEMO_TRACKING_CODE),
             summary="На консультации перед зачётом преподаватель потребовал купить его учебное пособие как условие допуска. "
                     "Это не указано в программе дисциплины.",
             created_at=now - timedelta(days=4),
             steps=[("accepted", timedelta(days=1), "Обращение принято. Проверим программу дисциплины и условия допуска.")])
        if boris is not None:
            make(category="grade", mode="open", author_id=boris.id,
                 summary="За контрольную работу 2 по корпоративным финансам снижен балл без комментариев, "
                         "хотя решение совпадает с разбором на семинаре. Прошу перепроверить.",
                 happened_on=(now - timedelta(days=7)).date(), created_at=now - timedelta(days=2),
                 steps=[("accepted", timedelta(hours=20), "Запросили работу и критерии оценивания у кафедры.")])
        make(category="pressure", mode="confidential", author_id=boris.id if boris else None,
             summary="Староста группы публично отмечает «прогульщиков» в общем чате и угрожает сообщить в деканат, "
                     "хотя пропуски были по уважительной причине.",
             created_at=now - timedelta(days=15))
        await db.commit()
        return counter.value


def register_complaint_routes(app: FastAPI, service: ComplaintService) -> None:
    require_session = app.state.require_session
    anonymous_limit = RateLimiter(limit=3, window=24 * 3600)
    track_limit = RateLimiter(limit=20, window=600)

    def parse(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(value)
        except ValueError:
            raise ApiError(404, "not_found", "Обращение не найдено.") from None

    @app.post("/api/complaints", status_code=201, tags=["complaints"])
    async def create(body: CreateBody, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        if body.mode == "anonymous":
            # In-memory only: hashed account and hashed address, never written anywhere.
            anonymous_limit.check(request, "complaint-anon-user", str(current.user.id))
            anonymous_limit.check(request, "complaint-anon-ip")
        row, code = await service.create(current.user, body)
        return {"complaint": service.payload(row), "tracking_code": code}

    @app.get("/api/complaints", tags=["complaints"])
    async def own(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": [service.payload(r) for r in await service.own(current.user)]}

    @app.get("/api/complaints/{complaint_id}", tags=["complaints"])
    async def own_one(complaint_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return service.payload(await service.get_own(current.user, parse(complaint_id)))

    @app.post("/api/complaints/track", tags=["public"])
    async def track(body: TrackBody, request: Request) -> dict:
        track_limit.check(request, "complaint-track")
        row = await service.track(body.code)
        if row is None:
            raise ApiError(404, "not_found", "Обращение с таким кодом не найдено.")
        data = service.payload(row)
        data.pop("summary", None)
        data.pop("context", None)
        return data

    @app.get("/api/admin/complaints", tags=["admin"])
    async def queue(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.queue(current.user)}

    @app.get("/api/admin/complaints/{complaint_id}", tags=["admin"])
    async def admin_one(complaint_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.admin_get(current.user, parse(complaint_id))

    @app.post("/api/admin/complaints/{complaint_id}/transition", tags=["admin"])
    async def transition(complaint_id: str, body: TransitionBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.transition(current.user, parse(complaint_id), body.to, body.note)

    @app.post("/api/admin/complaints/{complaint_id}/reveal", tags=["admin"])
    async def reveal(complaint_id: str, body: RevealBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.reveal(current.user, parse(complaint_id), body.reason)
