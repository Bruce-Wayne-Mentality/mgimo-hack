"""Seed the request catalogue and demo requests (section 13.3).

Demo set: Anna has a ready certificate and a request in work; Boris has one
waiting for his answer and one overdue by SLA (for the staff queue). Vera has
none, to show empty states. Times are relative to "now" so the demo stays fresh.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from sqlalchemy import func, select

from ..accounts.models import Staff, Student, User
from ..db import Database, utcnow
from .catalog import REQUEST_TYPES
from .models import RequestComment, RequestCounter, RequestEvent, RequestType, StudentRequest
from .service import MOSCOW, add_business_days


async def seed_request_types(database: Database) -> int:
    """Create missing types and refresh texts/fields of existing ones."""
    created = 0
    async with database.session() as db:
        existing = {row.code: row for row in (await db.scalars(select(RequestType))).all()}
        for data in REQUEST_TYPES:
            row = existing.get(data["code"])
            if row is None:
                db.add(RequestType(**data))
                created += 1
            else:
                for key, value in data.items():
                    setattr(row, key, value)
        await db.commit()
    return created


async def seed_demo_requests(database: Database, *, now: datetime | None = None) -> int:
    """Insert the demo requests once (skipped when any request exists)."""
    now = now or utcnow()
    async with database.session() as db:
        if await db.scalar(select(func.count()).select_from(StudentRequest)):
            return 0
        types = {row.code: row for row in (await db.scalars(select(RequestType))).all()}
        students = {
            user.login: student
            for user, student in (await db.execute(select(User, Student).join(Student, Student.user_id == User.id))).all()
        }
        staff_user = await db.scalar(select(User).join(Staff, Staff.user_id == User.id).where(User.login == "staff.deanery"))
        if not types or "student.anna" not in students or "student.boris" not in students:
            return 0

        year = now.astimezone(MOSCOW).year
        counter = await db.get(RequestCounter, year)
        if counter is None:
            counter = RequestCounter(year=year, value=0)
            db.add(counter)

        def make(login: str, code: str, payload: dict, created: datetime, steps: list[tuple[str, timedelta, str | None, bool]],
                 comments: list[tuple[bool, str, timedelta]] = ()) -> StudentRequest:
            counter.value += 1
            request_type = types[code]
            request = StudentRequest(
                number=f"ДК-{year}-{counter.value:06d}", student_id=students[login].id, type_id=request_type.id,
                status="submitted", payload=payload, created_at=created, updated_at=created,
                due_at=add_business_days(created, request_type.sla_days),
            )
            db.add(request)
            db.add(RequestEvent(request=request, from_status=None, to_status="submitted",
                                actor_id=students[login].user_id, at=created))
            status = "submitted"
            for to_status, offset, note, by_staff in steps:
                at = created + offset
                db.add(RequestEvent(request=request, from_status=status, to_status=to_status,
                                    actor_id=staff_user.id if by_staff and staff_user else None, at=at, note=note))
                status = to_status
                request.updated_at = at
                if to_status == "in_review" and by_staff and staff_user:
                    request.assignee_id = staff_user.id
                if to_status == "ready":
                    request.result_note = note
                    request.closed_at = at
            request.status = status
            for from_staff, body, offset in comments:
                author = staff_user.id if from_staff and staff_user else students[login].user_id
                db.add(RequestComment(request=request, author_id=author, body=body, created_at=created + offset))
            return request

        make("student.anna", "CERT_STUDY", {"destination": "По месту требования", "copies": 1}, now - timedelta(days=3),
             [("in_review", timedelta(seconds=1), None, False),
              ("ready", timedelta(seconds=2), "Справка сформирована автоматически.", False)])
        make("student.anna", "CERT_INTERN",
             {"organization": "ООО «Демо-Аналитика»", "period_from": (now + timedelta(days=20)).date().isoformat(),
              "period_to": (now + timedelta(days=50)).date().isoformat()},
             now - timedelta(days=1), [("in_review", timedelta(hours=3), None, True)])
        make("student.boris", "CERT_MIL", {"purpose": "deferment", "office": "Военкомат Демо-района"}, now - timedelta(days=2),
             [("in_review", timedelta(hours=2), None, True),
              ("needs_info", timedelta(hours=5), "Уточните полный адрес военкомата и номер приписного свидетельства.", True)],
             comments=[(True, "Уточните полный адрес военкомата и номер приписного свидетельства.", timedelta(hours=5))])
        make("student.boris", "RETAKE", {"discipline": "Эконометрика", "reason": "Болел в день экзамена, есть справка."},
             now - timedelta(days=6), [])
        await db.commit()
        return 4
