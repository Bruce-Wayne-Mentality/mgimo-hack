"""C5 / S1: deanery announcements with an audience (FR-NTF-5, FR-STF-4).

Audience: everyone, a faculty, a course of a faculty, or a group. A staff
member publishes only to their own faculty; admin to anyone. Publishing also
drops a notification into each addressee's notification centre.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr
from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Integer, String, Text, Uuid, or_, select
from sqlalchemy.orm import Mapped, mapped_column

from .accounts.models import AuditLog, Faculty, Student, StudyGroup, User
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Base, Database, UTCDateTime, utcnow, uuid7

AUDIENCE_LABELS = {"all": "Все студенты", "faculty": "Факультет", "course": "Курс", "group": "Группа"}


class Announcement(Base):
    __tablename__ = "announcements"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    author_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(String(16))
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("faculties.id", ondelete="CASCADE"), nullable=True)
    course: Mapped[int | None] = mapped_column(Integer, nullable=True)
    group_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), nullable=True)
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    important: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)

    __table_args__ = (CheckConstraint("audience IN ('all', 'faculty', 'course', 'group')", name="audience_known"),)


class AnnouncementBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: StrictStr = Field(min_length=3, max_length=200)
    body: StrictStr = Field(min_length=3, max_length=4000)
    audience: Literal["all", "faculty", "course", "group"]
    faculty_id: StrictStr | None = None
    course: int | None = Field(default=None, ge=1, le=6)
    group_id: StrictStr | None = None
    pinned: StrictBool = False
    important: StrictBool = False
    days: int = Field(default=14, ge=1, le=120)


def _matches(row: Announcement, group: StudyGroup) -> bool:
    if row.audience == "all":
        return True
    if row.audience == "faculty":
        return row.faculty_id == group.faculty_id
    if row.audience == "course":
        return row.faculty_id == group.faculty_id and row.course == group.course
    return row.group_id == group.id


class AnnouncementService:
    def __init__(self, database: Database, *, notify: Callable[[str, list[dict]], None] | None = None,
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.notify = notify
        self.clock = clock

    def payload(self, row: Announcement, labels: dict[str, str] | None = None) -> dict:
        return {
            "id": str(row.id), "title": row.title, "body": row.body, "author": row.author_name,
            "audience": row.audience, "audience_label": (labels or {}).get(str(row.id), AUDIENCE_LABELS[row.audience]),
            "pinned": row.pinned, "important": row.important,
            "created_at": row.created_at.isoformat(), "expires_at": row.expires_at.isoformat() if row.expires_at else None,
        }

    async def for_student(self, user: User) -> list[dict]:
        student = user.student
        if user.role != "student" or student is None:
            return []
        now = self.clock()
        async with self.database.session() as db:
            rows = list((await db.scalars(
                select(Announcement).where(Announcement.archived.is_(False),
                                           or_(Announcement.expires_at.is_(None), Announcement.expires_at > now))
                .order_by(Announcement.created_at.desc())
            )).all())
        items = [row for row in rows if _matches(row, student.group)]
        items.sort(key=lambda row: (not row.pinned, -row.created_at.timestamp()))
        return [self.payload(row) for row in items]

    async def staff_list(self, user: User) -> dict:
        self._require_staff(user)
        async with self.database.session() as db:
            rows = list((await db.scalars(
                select(Announcement).where(Announcement.archived.is_(False)).order_by(Announcement.created_at.desc())
            )).all())
            faculties = list((await db.scalars(select(Faculty).order_by(Faculty.title))).all())
            groups = list((await db.scalars(select(StudyGroup).order_by(StudyGroup.code))).all())
        if user.role == "staff":
            own = user.staff.faculty_id
            rows = [r for r in rows if r.faculty_id == own or (r.group_id and any(g.id == r.group_id and g.faculty_id == own for g in groups))]
            faculties = [f for f in faculties if f.id == own]
            groups = [g for g in groups if g.faculty_id == own]
        return {
            "items": [self.payload(row) for row in rows],
            "faculties": [{"id": str(f.id), "title": f.title} for f in faculties],
            "groups": [{"id": str(g.id), "code": g.code, "course": g.course, "faculty_id": str(g.faculty_id)} for g in groups],
            "can_all": user.role == "admin",
        }

    @staticmethod
    def _require_staff(user: User) -> None:
        if not user.is_active or user.role not in ("staff", "admin"):
            raise ApiError(403, "forbidden", "Объявления публикуют сотрудники деканата.")

    async def publish(self, user: User, body: AnnouncementBody) -> dict:
        self._require_staff(user)
        now = self.clock()
        async with self.database.session() as db:
            faculty_id = group_id = None
            if body.audience == "all":
                if user.role != "admin":
                    raise ApiError(403, "forbidden", "Сотрудник публикует объявления только для своего факультета.")
            elif body.audience in ("faculty", "course"):
                faculty_id = _uuid(body.faculty_id) if body.faculty_id else (user.staff.faculty_id if user.staff else None)
                if faculty_id is None or await db.get(Faculty, faculty_id) is None:
                    raise ApiError(422, "validation_failed", "Выберите факультет.", fields={"faculty_id": "Выберите факультет."})
                if body.audience == "course" and body.course is None:
                    raise ApiError(422, "validation_failed", "Выберите курс.", fields={"course": "Выберите курс."})
            else:
                group = await db.get(StudyGroup, _uuid(body.group_id)) if body.group_id else None
                if group is None:
                    raise ApiError(422, "validation_failed", "Выберите группу.", fields={"group_id": "Выберите группу."})
                group_id, faculty_id = group.id, group.faculty_id
            if user.role == "staff" and faculty_id != (user.staff.faculty_id if user.staff else None):
                raise ApiError(403, "forbidden", "Сотрудник публикует объявления только для своего факультета.")
            row = Announcement(
                author_id=user.id, author_name=user.display_name, title=body.title.strip(), body=body.body.strip(),
                audience=body.audience, faculty_id=faculty_id, course=body.course if body.audience == "course" else None,
                group_id=group_id, pinned=body.pinned, important=body.important, created_at=now,
                expires_at=now + timedelta(days=body.days),
            )
            db.add(row)
            await db.flush()
            students = list((await db.scalars(
                select(Student).join(User, Student.user_id == User.id).where(User.is_active.is_(True))
            )).all())
            recipients = [s.email for s in students if _matches(row, s.group)] if self.notify else []
            db.add(AuditLog(actor_id=user.id, action="announcement.publish", object_type="announcement",
                            object_id=str(row.id), meta={"audience": body.audience, "recipients": len(recipients)}))
            await db.commit()
            result = self.payload(row)
        for email in recipients:
            try:
                self.notify(email, [{
                    "event_key": f"announcement:{row.id}", "kind": "announcement",
                    "title": ("Важно: " if row.important else "Объявление: ") + row.title,
                    "body": row.body[:300], "payload": {"link": "/notifications?tab=announcements", "important": row.important},
                }])
            except Exception:
                pass
        result["recipients"] = len(recipients)
        return result

    async def archive(self, user: User, announcement_id: uuid.UUID) -> None:
        self._require_staff(user)
        async with self.database.session() as db:
            row = await db.get(Announcement, announcement_id)
            if row is None or (user.role == "staff" and row.faculty_id != (user.staff.faculty_id if user.staff else None)):
                raise ApiError(404, "not_found", "Объявление не найдено.")
            row.archived = True
            db.add(AuditLog(actor_id=user.id, action="announcement.archive", object_type="announcement", object_id=str(row.id)))
            await db.commit()


def _uuid(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


async def seed_announcements(database: Database, *, now: datetime | None = None) -> int:
    now = now or utcnow()
    async with database.session() as db:
        if await db.scalar(select(Announcement.id).limit(1)):
            return 0
        faculties = {f.code: f for f in (await db.scalars(select(Faculty))).all()}
        groups = {g.code: g for g in (await db.scalars(select(StudyGroup))).all()}
        if "ECON" not in faculties:
            return 0
        rows = [
            Announcement(author_name="Деканат (демо)", title="Расписание сессии опубликовано",
                         body="Расписание зачётов и экзаменов зимней сессии доступно в разделе «Учёба → Сессия». "
                              "Проверьте допуск по каждой дисциплине до 15 декабря.",
                         audience="all", pinned=True, important=True, created_at=now - timedelta(days=2),
                         expires_at=now + timedelta(days=40)),
            Announcement(author_name="Демченко О. В.", title="Продление приёма заявлений на материальную помощь",
                         body="Заявления на единовременную материальную помощь принимаются до конца месяца. "
                              "Подать можно в кабинете: «Заявки → Материальная помощь». Очного визита не нужно.",
                         audience="faculty", faculty_id=faculties["ECON"].id, created_at=now - timedelta(days=1),
                         expires_at=now + timedelta(days=14)),
            Announcement(author_name="Демченко О. В.", title="Консультация по курсовым работам",
                         body="В четверг в 16:20, ауд. Б-220 — консультация по оформлению курсовых работ. "
                              "Возьмите черновик: дедлайн черновика через 9 дней.",
                         audience="course", faculty_id=faculties["ECON"].id, course=3, created_at=now - timedelta(hours=20),
                         expires_at=now + timedelta(days=9)),
            Announcement(author_name="Деканат (демо)", title="Неделя карьеры: стажировки для первокурсников",
                         body="С 24 по 28 ноября — встречи с работодателями (все компании вымышленные). "
                              "Записаться можно у старосты группы.",
                         audience="faculty", faculty_id=faculties["IT"].id if "IT" in faculties else None,
                         created_at=now - timedelta(hours=6), expires_at=now + timedelta(days=12)),
        ]
        if "ЭК-25-1" in groups:
            rows.append(Announcement(author_name="Демченко О. В.", title="Замена аудитории по эконометрике",
                                     body="Практические занятия по эконометрике в четверг проходят в компьютерном классе Б-118.",
                                     audience="group", faculty_id=faculties["ECON"].id, group_id=groups["ЭК-25-1"].id,
                                     created_at=now - timedelta(hours=3), expires_at=now + timedelta(days=7)))
        for row in rows:
            if row.audience in ("faculty", "course") and row.faculty_id is None:
                continue
            db.add(row)
        await db.commit()
        return len(rows)


def register_announcement_routes(app: FastAPI, service: AnnouncementService) -> None:
    require_session = app.state.require_session

    @app.get("/api/announcements", tags=["announcements"])
    async def announcements(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.for_student(current.user)}

    @app.get("/api/staff/announcements", tags=["staff"])
    async def staff_announcements(current: CurrentSession = Depends(require_session)) -> dict:
        return await service.staff_list(current.user)

    @app.post("/api/staff/announcements", status_code=201, tags=["staff"])
    async def publish(body: AnnouncementBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.publish(current.user, body)

    @app.delete("/api/staff/announcements/{announcement_id}", status_code=204, tags=["staff"])
    async def archive(announcement_id: str, current: CurrentSession = Depends(require_session)) -> None:
        parsed = _uuid(announcement_id)
        if parsed is None:
            raise ApiError(404, "not_found", "Объявление не найдено.")
        await service.archive(current.user, parsed)
