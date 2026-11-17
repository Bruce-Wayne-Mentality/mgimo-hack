"""Staff dashboard, admin audit log and the demo reset (FR-GEN-1, S1, section 13)."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta

from fastapi import Depends, FastAPI, Query
from sqlalchemy import delete, func, select

from .accounts.models import AuditLog, Student, StudyGroup, User
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Base, Database, utcnow

ACTION_LABELS = {
    "login.success": "Вход", "login.failed": "Неудачный вход", "logout": "Выход", "logout_all": "Выход на всех устройствах",
    "password.change": "Смена пароля", "request.create": "Заявка создана", "request.transition": "Статус заявки",
    "request.comment": "Комментарий к заявке", "grade.set": "Оценка выставлена", "gradebook.view": "Просмотр журнала",
    "document.issue": "Документ выпущен", "document.download": "Документ скачан", "document.revoke": "Документ отозван",
    "announcement.publish": "Объявление опубликовано", "announcement.archive": "Объявление снято",
    "complaint.create": "Обращение подано", "complaint.transition": "Статус обращения",
    "complaint.reveal_author": "Раскрытие автора обращения", "demo.reset": "Сброс демо-данных",
}


def register_admin_routes(app: FastAPI, database: Database, store, *, demo: bool, reseed) -> None:
    require_session = app.state.require_session

    @app.get("/api/staff/dashboard", tags=["staff"])
    async def dashboard(current: CurrentSession = Depends(require_session)) -> dict:
        from .academics.service import AcademicService
        from .student_requests import policy
        from .student_requests.models import RequestType, StudentRequest
        from .student_requests.service import OPEN_STATUSES

        user = current.user
        if not user.is_active or user.role not in ("staff", "admin"):
            raise ApiError(403, "forbidden", "Панель доступна сотрудникам.")
        now = utcnow()
        async with database.session() as db:
            query = select(StudentRequest).join(Student, StudentRequest.student_id == Student.id) \
                .join(StudyGroup, Student.group_id == StudyGroup.id).join(RequestType, StudentRequest.type_id == RequestType.id)
            query = policy.scope_query(user, query, StudyGroup, RequestType)
            requests = list((await db.scalars(query)).unique().all())
        open_items = [r for r in requests if r.status in OPEN_STATUSES]
        week_ago = now - timedelta(days=7)
        closed_week = [r for r in requests if r.closed_at and r.closed_at >= week_ago]
        auto = sum(1 for r in closed_week if r.type.auto_issue)
        durations = [(r.closed_at - r.created_at).total_seconds() / 3600 for r in closed_week if not r.type.auto_issue]
        academics = AcademicService(database)
        groups = await academics.staff_groups(user)
        risk = Counter()
        at_risk: dict[str, dict] = {}
        for group in groups:
            for discipline in group["disciplines"]:
                book = await academics.gradebook(user, __import__("uuid").UUID(discipline["id"]), audit=False)
                for row in book["rows"]:
                    level = row["risk"]["level"]
                    risk[level] += 1
                    if level == "red":
                        entry = at_risk.setdefault(row["student_id"], {
                            "student": row["full_name"], "group": group["code"], "disciplines": [],
                            "discipline_id": discipline["id"], "discipline": discipline["title"],
                            "reason": row["risk"]["reasons"][0]["text"] if row["risk"]["reasons"] else "",
                        })
                        entry["disciplines"].append(discipline["title"])
        by_type = Counter(r.type.title for r in open_items)
        return {
            "requests": {
                "open": len(open_items),
                "submitted": sum(1 for r in open_items if r.status == "submitted"),
                "needs_info": sum(1 for r in open_items if r.status == "needs_info"),
                "overdue": sum(1 for r in open_items if r.status in ("submitted", "in_review") and r.due_at < now),
                "closed_week": len(closed_week),
                "auto_issued_week": auto,
                "avg_hours": round(sum(durations) / len(durations), 1) if durations else None,
                "by_type": [{"title": k, "count": v} for k, v in by_type.most_common()],
            },
            "risk": {"red": risk["red"], "yellow": risk["yellow"], "green": risk["green"], "grey": risk["grey"]},
            # One row per student, the most troubled first: who the deanery should write to first.
            "at_risk": sorted(at_risk.values(), key=lambda x: (-len(x["disciplines"]), x["group"], x["student"]))[:10],
            "groups": [{"code": g["code"], "course": g["course"], "students": g["students"]} for g in groups],
        }

    @app.get("/api/admin/audit", tags=["admin"])
    async def audit(limit: int = Query(default=100, ge=1, le=300), current: CurrentSession = Depends(require_session)) -> dict:
        if current.user.role != "admin":
            raise ApiError(404, "not_found", "Не найдено.")
        async with database.session() as db:
            rows = (await db.execute(
                select(AuditLog, User.login).join(User, AuditLog.actor_id == User.id, isouter=True)
                .order_by(AuditLog.at.desc()).limit(limit)
            )).all()
        return {"items": [
            {"id": str(row.id), "at": row.at.isoformat(), "actor": login or "система / аноним", "action": row.action,
             "action_label": ACTION_LABELS.get(row.action, row.action), "object_type": row.object_type,
             "object_id": row.object_id,
             "meta": {k: v for k, v in (row.meta or {}).items() if k not in ("reason",)}}
            for row, login in rows
        ]}

    @app.post("/api/admin/demo-reset", tags=["admin"])
    async def demo_reset(current: CurrentSession = Depends(require_session)) -> dict:
        """Wipe and re-create the demo data (only in --demo; admin only). Everyone is signed out."""
        if not demo:
            raise ApiError(404, "not_found", "Не найдено.")
        if current.user.role != "admin":
            raise ApiError(403, "forbidden", "Сбросить демо может только администратор.")
        async with database.session() as db:
            for table in reversed(Base.metadata.sorted_tables):
                await db.execute(delete(table))
            await db.commit()
        store.reset_feed()
        created = await reseed(database)
        async with database.session() as db:
            db.add(AuditLog(actor_id=None, action="demo.reset", meta={"by": "admin.demo"}))
            await db.commit()
        return {"ok": True, "created": {k: v for k, v in created.items() if isinstance(v, int)}}

    @app.get("/api/about", tags=["public"])
    async def about() -> dict:
        async with database.session() as db:
            students = await db.scalar(select(func.count()).select_from(Student))
        return {"demo": demo, "students": students}
