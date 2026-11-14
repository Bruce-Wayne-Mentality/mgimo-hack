"""Request lifecycle (C4 / K2): creation, status machine, history, comments.

Every transition is checked against TRANSITIONS on the server; anything else
is a 409, whatever the interface shows. Each transition writes a
request_events row and notifies the student.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts.models import AuditLog, Student, StudyGroup, User
from ..db import Database, utcnow
from . import policy
from .catalog import PayloadError, validate_payload
from .models import RequestComment, RequestCounter, RequestEvent, RequestType, StudentRequest

MOSCOW = ZoneInfo("Europe/Moscow")

STATUS_LABELS = {
    "submitted": "Принята",
    "in_review": "В работе",
    "needs_info": "Нужны данные",
    "ready": "Готова",
    "rejected": "Отклонена",
    "cancelled": "Отменена",
}
OPEN_STATUSES = ("submitted", "in_review", "needs_info")
CLOSED_STATUSES = ("ready", "rejected", "cancelled")

# (from, to) -> who may do it and whether a note is required (section 4.4).
TRANSITIONS: dict[tuple[str, str], dict] = {
    ("submitted", "in_review"): {"by": {"staff", "system"}, "note": False},
    ("in_review", "needs_info"): {"by": {"staff"}, "note": True},
    ("needs_info", "in_review"): {"by": {"student"}, "note": False},
    ("in_review", "ready"): {"by": {"staff", "system"}, "note": True},
    ("in_review", "rejected"): {"by": {"staff"}, "note": True},
    ("submitted", "cancelled"): {"by": {"student"}, "note": False},
    ("needs_info", "cancelled"): {"by": {"student"}, "note": False},
}
STUDENT_COMMENT_STATUSES = ("submitted", "in_review", "needs_info")
NOTE_MAX = 2000


class RequestError(Exception):
    def __init__(self, status: int, code: str, message: str, fields: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields


def not_found() -> RequestError:
    # Someone else's request looks exactly like a missing one (section 9.1).
    return RequestError(404, "not_found", "Заявка не найдена.")


def add_business_days(start: datetime, days: int) -> datetime:
    """SLA due date: skip Saturdays and Sundays in Moscow time."""
    local = start.astimezone(MOSCOW)
    if days <= 0:
        return (local + timedelta(hours=1)).astimezone(timezone.utc)
    added = 0
    while added < days:
        local += timedelta(days=1)
        if local.weekday() < 5:
            added += 1
    return local.replace(hour=18, minute=0, second=0, microsecond=0).astimezone(timezone.utc)


Notifier = Callable[[str, list[dict]], None]


@dataclass(frozen=True)
class Actor:
    user: User

    @property
    def kind(self) -> str:
        return "student" if self.user.role == "student" else "staff"


class RequestService:
    def __init__(self, database: Database, *, notify: Notifier | None = None, clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.notify = notify
        self.clock = clock

    # ---- catalogue -------------------------------------------------------

    async def list_types(self) -> list[RequestType]:
        async with self.database.session() as db:
            rows = await db.scalars(select(RequestType).where(RequestType.is_active).order_by(RequestType.sort))
            return list(rows.all())

    # ---- student side ----------------------------------------------------

    async def create(self, user: User, type_code: str, payload: object, idempotency_key: str | None) -> tuple[StudentRequest, bool]:
        """Returns (request, created). A repeated Idempotency-Key returns the first request."""
        student = self._student_of(user)
        if idempotency_key is not None and not (8 <= len(idempotency_key) <= 64):
            raise RequestError(422, "validation_failed", "Неверный ключ идемпотентности.", {"idempotency_key": "8–64 символа."})
        async with self.database.session() as db:
            if idempotency_key:
                existing = await self._by_key(db, student.id, idempotency_key)
                if existing is not None:
                    return existing, False
            request_type = await db.scalar(select(RequestType).where(RequestType.code == type_code, RequestType.is_active))
            if request_type is None:
                raise RequestError(422, "validation_failed", "Такого типа заявки нет.", {"type_code": "Выберите тип из каталога."})
            try:
                cleaned = validate_payload(request_type.fields, payload)
            except PayloadError as error:
                raise RequestError(422, "validation_failed", "Проверьте заполнение формы.", error.fields) from None
            now = self.clock()
            request = StudentRequest(
                number=await self._next_number(db, now),
                student_id=student.id,
                type_id=request_type.id,
                status="submitted",
                payload=cleaned,
                idempotency_key=idempotency_key,
                created_at=now,
                updated_at=now,
                due_at=add_business_days(now, request_type.sla_days),
            )
            request.type = request_type
            db.add(request)
            db.add(RequestEvent(request=request, from_status=None, to_status="submitted", actor_id=user.id, at=now))
            notes = [("submitted", None)]
            if request_type.auto_issue and student.status == "active":
                # K2 auto-issue: the system moves simple certificates to "ready" at once.
                self._move(db, request, "in_review", actor=None, now=now)
                self._move(db, request, "ready", actor=None, now=now, note="Справка сформирована автоматически.")
                notes = [("ready", "Справка сформирована автоматически.")]
            db.add(AuditLog(actor_id=user.id, action="request.created", object_type="request", object_id=str(request.id), at=now))
            try:
                await db.commit()
            except IntegrityError:
                await db.rollback()
                if idempotency_key:
                    existing = await self._by_key(db, student.id, idempotency_key)
                    if existing is not None:
                        return existing, False
                raise
        for status, note in notes:
            self._notify(student.email, request, status, note)
        return await self.get(user, request.id), True

    async def list_own(self, user: User) -> list[StudentRequest]:
        student = self._student_of(user)
        async with self.database.session() as db:
            rows = await db.scalars(
                select(StudentRequest).where(StudentRequest.student_id == student.id).order_by(StudentRequest.created_at.desc())
            )
            return list(rows.unique().all())

    async def get(self, user: User, request_id: uuid.UUID) -> StudentRequest:
        async with self.database.session() as db:
            request = await self._load(db, request_id)
            if request is None or not await self._can_view(db, user, request):
                raise not_found()
            return request

    async def cancel(self, user: User, request_id: uuid.UUID) -> StudentRequest:
        return await self._student_transition(user, request_id, "cancelled")

    async def comment(self, user: User, request_id: uuid.UUID, body: str, *, internal: bool = False) -> StudentRequest:
        body = body.strip()
        if not body:
            raise RequestError(422, "validation_failed", "Напишите сообщение.", {"body": "Напишите сообщение."})
        if len(body) > NOTE_MAX:
            raise RequestError(422, "validation_failed", f"Не больше {NOTE_MAX} символов.", {"body": f"Не больше {NOTE_MAX} символов."})
        actor = Actor(user)
        if actor.kind == "student" and internal:
            raise RequestError(403, "forbidden", "Внутренние заметки доступны только сотрудникам.")
        now = self.clock()
        async with self.database.session() as db:
            request = await self._load(db, request_id, lock=True)
            if request is None or not await self._can_view(db, user, request):
                raise not_found()
            if actor.kind == "student" and request.status not in STUDENT_COMMENT_STATUSES:
                raise RequestError(409, "invalid_state", "По закрытой заявке писать нельзя.")
            db.add(RequestComment(request=request, author_id=user.id, body=body, internal=internal, created_at=now))
            if actor.kind == "student" and request.status == "needs_info":
                # FR-REQ-5: the student's answer sends the request back to work.
                self._move(db, request, "in_review", actor=user, now=now, note="Ответ студента")
            request.updated_at = now
            await db.commit()
            email = request.student.email
        # The student wrote it themselves, so only staff replies notify.
        if actor.kind == "staff" and not internal:
            self._notify(email, request, None, body, kind="comment")
        return await self.get(user, request_id)

    # ---- staff side ------------------------------------------------------

    async def staff_queue(self, user: User, *, status: str | None = None, type_code: str | None = None, overdue: bool = False) -> list[StudentRequest]:
        if not policy.is_staff(user):
            raise RequestError(403, "forbidden", "Очередь доступна сотрудникам деканата.")
        now = self.clock()
        async with self.database.session() as db:
            query = (
                select(StudentRequest)
                .join(StudentRequest.type)
                .join(StudentRequest.student)
                .join(Student.group)
                .order_by(StudentRequest.due_at.asc())
            )
            query = policy.scope_query(user, query, StudyGroup, RequestType)
            if status == "open":
                query = query.where(StudentRequest.status.in_(OPEN_STATUSES))
            elif status:
                query = query.where(StudentRequest.status == status)
            if type_code:
                query = query.where(RequestType.code == type_code)
            if overdue:
                query = query.where(StudentRequest.status.in_(OPEN_STATUSES), StudentRequest.due_at < now)
            rows = await db.scalars(query.limit(200))
            return list(rows.unique().all())

    async def staff_transition(self, user: User, request_id: uuid.UUID, to_status: str, note: str | None) -> StudentRequest:
        if not policy.is_staff(user):
            raise RequestError(403, "forbidden", "Действие доступно сотрудникам деканата.")
        note = (note or "").strip() or None
        if note and len(note) > NOTE_MAX:
            raise RequestError(422, "validation_failed", f"Не больше {NOTE_MAX} символов.", {"note": f"Не больше {NOTE_MAX} символов."})
        now = self.clock()
        async with self.database.session() as db:
            request = await self._load(db, request_id, lock=True)
            if request is None or not await self._can_view(db, user, request):
                raise not_found()
            rule = TRANSITIONS.get((request.status, to_status))
            if rule is None or "staff" not in rule["by"]:
                raise RequestError(409, "invalid_transition",
                                   f"Из статуса «{STATUS_LABELS[request.status]}» нельзя перейти в «{STATUS_LABELS.get(to_status, to_status)}».")
            if rule["note"] and not note:
                raise RequestError(422, "validation_failed", "Нужен комментарий для студента.", {"note": "Обязательное поле для этого перехода."})
            if to_status == "in_review" and request.assignee_id is None:
                request.assignee_id = user.id
            if to_status == "ready":
                request.result_note = note
            self._move(db, request, to_status, actor=user, now=now, note=note)
            db.add(AuditLog(actor_id=user.id, action=f"request.{to_status}", object_type="request", object_id=str(request.id), at=now))
            await db.commit()
            email = request.student.email
        self._notify(email, request, to_status, note)
        return await self.get(user, request_id)

    # ---- helpers ---------------------------------------------------------

    async def _student_transition(self, user: User, request_id: uuid.UUID, to_status: str) -> StudentRequest:
        now = self.clock()
        async with self.database.session() as db:
            request = await self._load(db, request_id, lock=True)
            if request is None or not await self._can_view(db, user, request) or user.role != "student":
                raise not_found()
            rule = TRANSITIONS.get((request.status, to_status))
            if rule is None or "student" not in rule["by"]:
                raise RequestError(409, "invalid_transition",
                                   f"Заявку в статусе «{STATUS_LABELS[request.status]}» нельзя {'отменить' if to_status == 'cancelled' else 'изменить'}.")
            self._move(db, request, to_status, actor=user, now=now)
            await db.commit()
        return await self.get(user, request_id)

    def _move(self, db: AsyncSession, request: StudentRequest, to_status: str, *, actor: User | None, now: datetime, note: str | None = None) -> None:
        db.add(RequestEvent(request=request, from_status=request.status, to_status=to_status,
                            actor_id=actor.id if actor else None, at=now, note=note))
        request.status = to_status
        request.updated_at = now
        if to_status in CLOSED_STATUSES:
            request.closed_at = now

    def _notify(self, email: str, request: StudentRequest, status: str | None, note: str | None, *, kind: str = "status") -> None:
        if self.notify is None:
            return
        if kind == "comment":
            title = f"Новое сообщение по заявке {request.number}"
            body = note or ""
            key = f"request:{request.id}:comment:{self.clock().timestamp()}"
        else:
            title = f"Заявка {request.number}: {STATUS_LABELS[status]}"
            body = request.type.title + (f". {note}" if note and status in ("needs_info", "rejected", "ready") else "")
            key = f"request:{request.id}:{status}:{self.clock().timestamp()}"
        try:
            self.notify(email, [{"event_key": key, "kind": "request", "title": title, "body": body[:500],
                                 "payload": {"link": f"/requests/{request.id}", "request_id": str(request.id)}}])
        except Exception:  # notifications must never break the request itself
            pass

    @staticmethod
    def _student_of(user: User) -> Student:
        if user.role != "student" or user.student is None:
            raise RequestError(403, "forbidden", "Заявки подают студенты.")
        return user.student

    async def _next_number(self, db: AsyncSession, now: datetime) -> str:
        year = now.astimezone(MOSCOW).year
        counter = await db.scalar(select(RequestCounter).where(RequestCounter.year == year).with_for_update())
        if counter is None:
            counter = RequestCounter(year=year, value=0)
            db.add(counter)
        counter.value += 1
        return f"ДК-{year}-{counter.value:06d}"

    async def _by_key(self, db: AsyncSession, student_id: uuid.UUID, key: str) -> StudentRequest | None:
        request = await db.scalar(
            select(StudentRequest).where(StudentRequest.student_id == student_id, StudentRequest.idempotency_key == key)
        )
        return request

    async def _load(self, db: AsyncSession, request_id: uuid.UUID, *, lock: bool = False) -> StudentRequest | None:
        query = select(StudentRequest).where(StudentRequest.id == request_id)
        if lock:
            query = query.with_for_update(of=StudentRequest)
        return await db.scalar(query)

    async def _can_view(self, db: AsyncSession, user: User, request: StudentRequest) -> bool:
        return policy.can_view_request(user, request)

    async def counts(self, user: User) -> dict[str, int]:
        student = self._student_of(user)
        async with self.database.session() as db:
            rows = await db.execute(
                select(StudentRequest.status, func.count()).where(StudentRequest.student_id == student.id).group_by(StudentRequest.status)
            )
            return {status: count for status, count in rows.all()}
