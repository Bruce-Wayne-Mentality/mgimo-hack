"""C3 «Успеваемость», K1 traffic light, S1 gradebook (FR-STF-6) and K5 nudges.

Access rules (section 10.2): a student sees only the disciplines of their own
group and only their own scores; staff see groups of their faculty; admin
sees everything. Someone else's object looks exactly like a missing one.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from ..accounts.models import AuditLog, Student, StudyGroup, User
from ..accounts.router import ApiError
from ..db import Database, utcnow
from . import risk
from .models import (
    CONTROL_LABELS,
    Attendance,
    Checkpoint,
    Discipline,
    Grade,
    GradeChange,
    Nudge,
    NudgeMute,
    PastResult,
    RiskSnapshot,
)

MOSCOW = ZoneInfo("Europe/Moscow")
Notifier = Callable[[str, list[dict]], None]

NUDGE_RULES = {
    "RISK_UP": "Риск по дисциплине",
    "DEADLINE_3D": "Скоро дедлайн",
    "SESSION_14D": "Скоро сессия",
    "REQ_STALE": "Деканат ждёт ответа",
}
NUDGES_PER_DAY = 2


def not_found(what: str = "Дисциплина не найдена.") -> ApiError:
    return ApiError(404, "not_found", what)


def moscow_today(now: datetime) -> date:
    return now.astimezone(MOSCOW).date()


def round_score(value: float) -> float:
    return round(float(value), 2)


class AcademicService:
    def __init__(self, database: Database, *, notify: Notifier | None = None,
                 clock: Callable[[], datetime] = utcnow, config: risk.RiskConfig = risk.DEFAULT) -> None:
        self.database = database
        self.notify = notify
        self.clock = clock
        self.config = config

    # ---- helpers ---------------------------------------------------------

    @staticmethod
    def _student_of(user: User) -> Student:
        if user.role != "student" or user.student is None:
            raise ApiError(403, "forbidden", "Раздел доступен студентам.")
        return user.student

    @staticmethod
    def _is_staff(user: User) -> bool:
        return user.is_active and user.role in ("staff", "admin")

    @staticmethod
    def _staff_can_see_group(user: User, group: StudyGroup) -> bool:
        if user.role == "admin":
            return True
        return user.role == "staff" and user.staff is not None and user.staff.faculty_id == group.faculty_id

    async def _disciplines(self, db: AsyncSession, group_id: uuid.UUID) -> list[Discipline]:
        rows = await db.scalars(
            select(Discipline).where(Discipline.group_id == group_id).order_by(Discipline.title)
        )
        return list(rows.all())

    async def _scores(self, db: AsyncSession, student_id: uuid.UUID, checkpoint_ids: list[uuid.UUID]) -> dict[uuid.UUID, Grade]:
        if not checkpoint_ids:
            return {}
        rows = await db.scalars(
            select(Grade).where(Grade.student_id == student_id, Grade.checkpoint_id.in_(checkpoint_ids))
        )
        return {row.checkpoint_id: row for row in rows.all()}

    async def _attendance(self, db: AsyncSession, student_id: uuid.UUID) -> dict[uuid.UUID, Attendance]:
        rows = await db.scalars(select(Attendance).where(Attendance.student_id == student_id))
        return {row.discipline_id: row for row in rows.all()}

    def _inputs(self, discipline: Discipline, scores: dict[uuid.UUID, Grade],
                override: dict[uuid.UUID, float | None] | None = None) -> list[risk.CheckpointInput]:
        items = []
        for checkpoint in discipline.checkpoints:
            score = scores[checkpoint.id].score if checkpoint.id in scores else None
            if override and checkpoint.id in override:
                score = override[checkpoint.id]
            items.append(risk.CheckpointInput(
                weight=checkpoint.weight, max_score=checkpoint.max_score, due_on=checkpoint.due_on,
                score=score, critical=checkpoint.critical, title=checkpoint.title,
            ))
        return items

    def _risk(self, discipline: Discipline, scores: dict, attendance: Attendance | None, today: date,
              override: dict | None = None) -> risk.RiskResult:
        return risk.compute(
            self._inputs(discipline, scores, override), today=today,
            threshold=discipline.admission_threshold,
            attended=attendance.attended if attendance else 0,
            total_lessons=attendance.total if attendance else 0,
            config=self.config,
        )

    @staticmethod
    def _actions(discipline: Discipline, result: risk.RiskResult) -> list[dict]:
        actions: list[dict] = []
        seen: set[str] = set()
        for code in result.reasons:
            action = risk.REASON_ACTION.get(code)
            if action and action["kind"] not in seen:
                seen.add(action["kind"])
                actions.append(dict(action))
        actions.append({"kind": "assistant", "label": "Спросить ассистента"})
        for action in actions:
            if action["kind"] == "retake":
                action["link"] = f"/requests/new?type=RETAKE&discipline={discipline.title}"
            elif action["kind"] == "assistant":
                action["link"] = f"/assistant?about={discipline.title}"
            elif action["kind"] == "consultation":
                action["link"] = f"/assistant?about={discipline.title}&intent=consultation"
            elif action["kind"] == "excuse":
                action["link"] = f"/assistant?about={discipline.title}&intent=attendance"
        return actions

    def _summary(self, discipline: Discipline, scores: dict, attendance: Attendance | None, today: date) -> dict:
        result = self._risk(discipline, scores, attendance, today)
        upcoming = next(
            (c for c in discipline.checkpoints if c.due_on and c.due_on >= today and c.id not in scores), None
        )
        return {
            "id": str(discipline.id),
            "code": discipline.code,
            "title": discipline.title,
            "teacher": discipline.teacher_name,
            "control_form": discipline.control_form,
            "control_label": CONTROL_LABELS[discipline.control_form],
            "credits": discipline.credits,
            "threshold": discipline.admission_threshold,
            "risk": result.to_dict(),
            "expected_by_today": risk.expected_by_today(self._inputs(discipline, scores), today),
            "next_checkpoint": None if upcoming is None else {
                "title": upcoming.title, "due_on": upcoming.due_on.isoformat(), "weight": upcoming.weight,
                "days_left": (upcoming.due_on - today).days,
            },
            "final_at": discipline.final_at.isoformat() if discipline.final_at else None,
            "final_room": discipline.final_room,
            "actions": self._actions(discipline, result),
        }

    # ---- student ---------------------------------------------------------

    async def overview(self, user: User) -> dict:
        student = self._student_of(user)
        today = moscow_today(self.clock())
        async with self.database.session() as db:
            disciplines = await self._disciplines(db, student.group_id)
            checkpoint_ids = [c.id for d in disciplines for c in d.checkpoints]
            scores = await self._scores(db, student.id, checkpoint_ids)
            attendance = await self._attendance(db, student.id)
            past = list((await db.scalars(
                select(PastResult).where(PastResult.student_id == student.id).order_by(PastResult.semester_no, PastResult.title)
            )).all())
        items = [self._summary(d, scores, attendance.get(d.id), today) for d in disciplines]
        items.sort(key=lambda item: (risk.LEVEL_ORDER[item["risk"]["level"]], item["title"]))
        counts = {level: sum(1 for item in items if item["risk"]["level"] == level) for level in risk.LEVEL_ORDER}
        with_data = len(items) - counts["grey"]
        semesters: dict[int, dict] = {}
        for row in past:
            entry = semesters.setdefault(row.semester_no, {"no": row.semester_no, "label": row.semester, "marks": [], "items": []})
            if row.mark is not None:
                entry["marks"].append(row.mark)
            entry["items"].append({
                "title": row.title, "control_label": CONTROL_LABELS[row.control_form], "credits": row.credits,
                "mark": row.mark, "passed": row.passed,
            })
        dynamics = []
        for entry in sorted(semesters.values(), key=lambda e: e["no"]):
            marks = entry.pop("marks")
            entry["average"] = round(sum(marks) / len(marks), 2) if marks else None
            dynamics.append(entry)
        all_marks = [row.mark for row in past if row.mark is not None]
        session = sorted(
            (
                {
                    "discipline_id": item["id"], "title": item["title"], "control_label": item["control_label"],
                    "at": item["final_at"], "room": item["final_room"],
                    "admission": {"green": "Допуск: да (предварительно)", "yellow": "Допуск: условный",
                                  "red": "Допуск: под вопросом", "grey": "Допуск: пока нет данных"}[item["risk"]["level"]],
                    "level": item["risk"]["level"],
                }
                for item in items if item["final_at"]
            ),
            key=lambda row: row["at"],
        )
        return {
            "semester": disciplines[0].semester if disciplines else None,
            "today": today.isoformat(),
            "summary": {
                "total": len(items),
                "on_track": counts["green"],
                "with_data": with_data,
                "counts": counts,
                "headline": (
                    "Оценок ещё нет" if not items
                    else f"В графике по {counts['green']} из {len(items)} {_plural(len(items), 'дисциплины', 'дисциплин', 'дисциплин')}"
                ),
            },
            "disciplines": items,
            "gpa": round(sum(all_marks) / len(all_marks), 2) if all_marks else None,
            "dynamics": dynamics,
            "session": session,
            "rules": risk.RULES_TEXT,
        }

    async def _own_discipline(self, db: AsyncSession, user: User, discipline_id: uuid.UUID) -> tuple[Student, Discipline]:
        student = self._student_of(user)
        discipline = await db.get(Discipline, discipline_id)
        if discipline is None or discipline.group_id != student.group_id:
            raise not_found()
        return student, discipline

    async def discipline(self, user: User, discipline_id: uuid.UUID) -> dict:
        today = moscow_today(self.clock())
        async with self.database.session() as db:
            student, discipline = await self._own_discipline(db, user, discipline_id)
            scores = await self._scores(db, student.id, [c.id for c in discipline.checkpoints])
            attendance = (await self._attendance(db, student.id)).get(discipline.id)
            history = list((await db.scalars(
                select(GradeChange).where(
                    GradeChange.student_id == student.id,
                    GradeChange.checkpoint_id.in_([c.id for c in discipline.checkpoints]),
                ).order_by(GradeChange.at.desc())
            )).all())
            snapshots = list((await db.scalars(
                select(RiskSnapshot).where(RiskSnapshot.student_id == student.id, RiskSnapshot.discipline_id == discipline.id)
                .order_by(RiskSnapshot.computed_at)
            )).all())
        return self._detail(discipline, scores, attendance, history, snapshots, today)

    def _detail(self, discipline, scores, attendance, history, snapshots, today) -> dict:
        titles = {c.id: c.title for c in discipline.checkpoints}
        data = self._summary(discipline, scores, attendance, today)
        result = self._risk(discipline, scores, attendance, today)
        remaining = sum(c.weight for c in discipline.checkpoints if c.id not in scores)
        data.update({
            "checkpoints": [
                {
                    "id": str(c.id), "title": c.title, "weight": c.weight, "max_score": c.max_score,
                    "due_on": c.due_on.isoformat() if c.due_on else None, "critical": c.critical, "is_final": c.is_final,
                    "score": scores[c.id].score if c.id in scores else None,
                    "points": round(c.weight * scores[c.id].score / c.max_score, 1) if c.id in scores else None,
                    "state": (
                        "graded" if c.id in scores
                        else "missed" if c.due_on and c.due_on + timedelta(days=self.config.grace_days) < today
                        else "waiting" if c.due_on and c.due_on <= today
                        else "upcoming"
                    ),
                }
                for c in discipline.checkpoints
            ],
            "attendance": None if attendance is None else {"attended": attendance.attended, "total": attendance.total},
            "history": [
                {"checkpoint": titles.get(h.checkpoint_id, "—"), "old": h.old_score, "new": h.new_score,
                 "by": h.changed_by_name, "at": h.at.isoformat(), "reason": h.reason}
                for h in history
            ],
            "trend": [{"level": s.level, "at": s.computed_at.isoformat(), "points": round(s.p, 1)} for s in snapshots],
            "remaining_weight": remaining,
            "need_for_admission": risk.needed_for(discipline.admission_threshold, result, remaining),
            "need_for_excellent": risk.needed_for(85, result, remaining),
        })
        return data

    async def what_if(self, user: User, discipline_id: uuid.UUID, hypothetical: dict[str, float]) -> dict:
        """«Что если»: recompute the light with imagined scores. Nothing is stored."""
        today = moscow_today(self.clock())
        async with self.database.session() as db:
            student, discipline = await self._own_discipline(db, user, discipline_id)
            scores = await self._scores(db, student.id, [c.id for c in discipline.checkpoints])
            attendance = (await self._attendance(db, student.id)).get(discipline.id)
        by_id = {str(c.id): c for c in discipline.checkpoints}
        override: dict[uuid.UUID, float | None] = {}
        errors = {}
        for key, value in hypothetical.items():
            checkpoint = by_id.get(key)
            if checkpoint is None:
                errors[key] = "Нет такой контрольной точки."
            elif checkpoint.id in scores:
                errors[key] = "Балл уже выставлен."
            elif not 0 <= value <= checkpoint.max_score:
                errors[key] = f"От 0 до {checkpoint.max_score}."
            else:
                override[checkpoint.id] = value
        if errors:
            raise ApiError(422, "validation_failed", "Проверьте баллы.", fields=errors)
        # Imagined scores count as if their deadline had already come: that is the question being asked.
        from dataclasses import replace

        names = {c.id: c.title for c in discipline.checkpoints}
        imagined = {names[cid] for cid in override}
        inputs = [
            replace(item, due_on=min(item.due_on or today, today)) if item.title in imagined else item
            for item in self._inputs(discipline, scores, override)
        ]
        result = risk.compute(
            inputs, today=today, threshold=discipline.admission_threshold,
            attended=attendance.attended if attendance else 0,
            total_lessons=attendance.total if attendance else 0, config=self.config,
        )
        total = sum(
            c.weight * (override.get(c.id, scores[c.id].score if c.id in scores else 0) or 0) / c.max_score
            for c in discipline.checkpoints
        )
        return {"total": round(total, 1), "risk": result.to_dict(),
                "passes": total >= discipline.admission_threshold,
                "mark": _mark_for(total)}

    # ---- staff: gradebook (FR-STF-6) ----------------------------------------

    async def staff_groups(self, user: User) -> list[dict]:
        if not self._is_staff(user):
            raise ApiError(403, "forbidden", "Раздел доступен сотрудникам деканата.")
        async with self.database.session() as db:
            groups = list((await db.scalars(select(StudyGroup).order_by(StudyGroup.code))).all())
            result = []
            for group in groups:
                if not self._staff_can_see_group(user, group):
                    continue
                disciplines = await self._disciplines(db, group.id)
                students = list((await db.scalars(select(Student).where(Student.group_id == group.id))).all())
                if not disciplines:
                    continue
                result.append({
                    "id": str(group.id), "code": group.code, "course": group.course, "faculty": group.faculty.title,
                    "students": len(students),
                    "disciplines": [{"id": str(d.id), "title": d.title, "control_label": CONTROL_LABELS[d.control_form]} for d in disciplines],
                })
            return result

    async def _staff_discipline(self, db: AsyncSession, user: User, discipline_id: uuid.UUID) -> tuple[Discipline, StudyGroup]:
        if not self._is_staff(user):
            raise not_found()
        discipline = await db.get(Discipline, discipline_id)
        if discipline is None:
            raise not_found()
        group = await db.get(StudyGroup, discipline.group_id)
        if group is None or not self._staff_can_see_group(user, group):
            raise not_found()
        return discipline, group

    async def gradebook(self, user: User, discipline_id: uuid.UUID, *, audit: bool = True) -> dict:
        today = moscow_today(self.clock())
        async with self.database.session() as db:
            discipline, group = await self._staff_discipline(db, user, discipline_id)
            students = list((await db.scalars(
                select(Student).where(Student.group_id == group.id).order_by(Student.full_name)
            )).all())
            checkpoint_ids = [c.id for c in discipline.checkpoints]
            grades = list((await db.scalars(select(Grade).where(Grade.checkpoint_id.in_(checkpoint_ids)))).all())
            attendance = {
                row.student_id: row for row in (await db.scalars(
                    select(Attendance).where(Attendance.discipline_id == discipline.id)
                )).all()
            }
            if audit:  # FR-STF-7: reading students' records is logged
                db.add(AuditLog(actor_id=user.id, action="gradebook.view", object_type="discipline", object_id=str(discipline.id)))
                await db.commit()
        by_student: dict[uuid.UUID, dict[uuid.UUID, Grade]] = {}
        for grade in grades:
            by_student.setdefault(grade.student_id, {})[grade.checkpoint_id] = grade
        rows = []
        for student in students:
            scores = by_student.get(student.id, {})
            result = self._risk(discipline, scores, attendance.get(student.id), today)
            rows.append({
                "student_id": str(student.id), "full_name": student.full_name, "record_book_no": student.record_book_no,
                "scores": {str(cid): grade.score for cid, grade in scores.items()},
                "risk": result.to_dict(),
            })
        counts = {level: sum(1 for row in rows if row["risk"]["level"] == level) for level in risk.LEVEL_ORDER}
        return {
            "discipline": {"id": str(discipline.id), "title": discipline.title, "teacher": discipline.teacher_name,
                           "control_label": CONTROL_LABELS[discipline.control_form]},
            "group": {"code": group.code, "course": group.course},
            "checkpoints": [
                {"id": str(c.id), "title": c.title, "weight": c.weight, "max_score": c.max_score,
                 "due_on": c.due_on.isoformat() if c.due_on else None, "critical": c.critical}
                for c in discipline.checkpoints
            ],
            "rows": rows,
            "counts": counts,
        }

    async def set_grade(self, user: User, discipline_id: uuid.UUID, student_id: uuid.UUID, checkpoint_id: uuid.UUID,
                        score: float | None, reason: str | None) -> dict:
        now = self.clock()
        today = moscow_today(now)
        reason = (reason or "").strip() or None
        async with self.database.session() as db:
            discipline, group = await self._staff_discipline(db, user, discipline_id)
            checkpoint = next((c for c in discipline.checkpoints if c.id == checkpoint_id), None)
            student = await db.get(Student, student_id)
            if checkpoint is None or student is None or student.group_id != group.id:
                raise not_found("Студент или контрольная точка не найдены.")
            if score is not None and not 0 <= score <= checkpoint.max_score:
                raise ApiError(422, "validation_failed", f"Балл от 0 до {checkpoint.max_score}.",
                               fields={"score": f"От 0 до {checkpoint.max_score}."})
            if score is not None:
                score = round_score(score)
            existing = await db.scalar(select(Grade).where(Grade.student_id == student.id, Grade.checkpoint_id == checkpoint.id))
            old = existing.score if existing else None
            if old is not None and score != old and reason is None:
                raise ApiError(422, "validation_failed", "Укажите причину изменения оценки.",
                               fields={"reason": "Причина обязательна при исправлении балла."})
            if old == score:
                return await self._gradebook_row(db, discipline, student, today)
            before = await self._level(db, discipline, student, today)
            if score is None:
                await db.delete(existing)
            elif existing is None:
                db.add(Grade(student_id=student.id, checkpoint_id=checkpoint.id, score=score, graded_at=now, graded_by=user.id))
            else:
                existing.score = score
                existing.graded_at = now
                existing.graded_by = user.id
            db.add(GradeChange(student_id=student.id, checkpoint_id=checkpoint.id, old_score=old, new_score=score,
                               changed_by=user.id, changed_by_name=user.display_name, reason=reason, at=now))
            db.add(AuditLog(actor_id=user.id, action="grade.set", object_type="grade",
                            object_id=f"{student.id}:{checkpoint.id}",
                            meta={"old": old, "new": score, "discipline": discipline.code}))
            await db.flush()
            after_result = await self._snapshot(db, discipline, student, today, now)
            row = await self._gradebook_row(db, discipline, student, today)
            email = student.email
            await db.commit()
        self._notify_grade(email, discipline, checkpoint, score, old, before, after_result)
        return row

    async def _level(self, db, discipline, student, today) -> str:
        scores = await self._scores(db, student.id, [c.id for c in discipline.checkpoints])
        attendance = await db.get(Attendance, (student.id, discipline.id))
        return self._risk(discipline, scores, attendance, today).level

    async def _gradebook_row(self, db, discipline, student, today) -> dict:
        scores = await self._scores(db, student.id, [c.id for c in discipline.checkpoints])
        attendance = await db.get(Attendance, (student.id, discipline.id))
        result = self._risk(discipline, scores, attendance, today)
        return {"student_id": str(student.id), "full_name": student.full_name, "record_book_no": student.record_book_no,
                "scores": {str(cid): grade.score for cid, grade in scores.items()}, "risk": result.to_dict()}

    async def _snapshot(self, db, discipline, student, today, now) -> risk.RiskResult:
        scores = await self._scores(db, student.id, [c.id for c in discipline.checkpoints])
        attendance = await db.get(Attendance, (student.id, discipline.id))
        result = self._risk(discipline, scores, attendance, today)
        last = await db.scalar(
            select(RiskSnapshot).where(RiskSnapshot.student_id == student.id, RiskSnapshot.discipline_id == discipline.id)
            .order_by(RiskSnapshot.computed_at.desc()).limit(1)
        )
        if last is None or last.level != result.level or abs(last.p - result.p) >= 0.05:
            db.add(RiskSnapshot(student_id=student.id, discipline_id=discipline.id, level=result.level, p=result.p,
                                w=result.w, pace=result.pace, r=result.r, reasons=list(result.reasons), computed_at=now))
        return result

    def _notify_grade(self, email, discipline, checkpoint, score, old, before: str, after: risk.RiskResult) -> None:
        if self.notify is None:
            return
        stamp = self.clock().timestamp()
        drafts = []
        if score is not None:
            title = "Новая оценка" if old is None else "Оценка исправлена"
            drafts.append({
                "event_key": f"grade:{checkpoint.id}:{stamp}", "kind": "grade", "title": f"{title}: {discipline.title}",
                "body": f"{checkpoint.title}: {score:g} из {checkpoint.max_score}" + (f" (было {old:g})" if old is not None else ""),
                "payload": {"link": f"/study/{discipline.id}"},
            })
        if risk.LEVEL_ORDER.get(after.level, 3) < risk.LEVEL_ORDER.get(before, 3) and after.level in ("yellow", "red"):
            reason = risk.REASON_TEXT[after.reasons[0]] if after.reasons else ""
            drafts.append({
                "event_key": f"risk:{discipline.id}:{after.level}:{stamp}", "kind": "risk",
                "title": f"{after.label}: {discipline.title}",
                "body": f"{reason}. Откройте дисциплину — там понятный следующий шаг.",
                "payload": {"link": f"/study/{discipline.id}"},
            })
        if not drafts:
            return
        try:
            self.notify(email, drafts)
        except Exception:
            pass

    # ---- K5: «Деканат пишет первым» ---------------------------------------

    async def nudges(self, user: User) -> list[dict]:
        """Generate due hints (deduplicated per rule+object+day) and return the active ones."""
        from ..student_requests.models import StudentRequest

        student = self._student_of(user)
        now = self.clock()
        today = moscow_today(now)
        async with self.database.session() as db:
            muted = set((await db.scalars(select(NudgeMute.rule_code).where(NudgeMute.student_id == student.id))).all())
            disciplines = await self._disciplines(db, student.group_id)
            scores = await self._scores(db, student.id, [c.id for d in disciplines for c in d.checkpoints])
            attendance = await self._attendance(db, student.id)
            candidates: list[dict] = []
            for discipline in disciplines:
                result = self._risk(discipline, scores, attendance.get(discipline.id), today)
                if result.level in ("red", "yellow"):
                    reason = risk.REASON_TEXT[result.reasons[0]].lower() if result.reasons else ""
                    candidates.append({
                        "rule": "RISK_UP", "key": f"RISK_UP:{discipline.id}:{result.level}",
                        "title": f"{result.label}: {discipline.title}",
                        "text": f"Причина — {reason}. Давайте разберёмся, пока до сессии есть время.",
                        "action": {"label": "Что делать", "link": f"/study/{discipline.id}"},
                        "priority": 0 if result.level == "red" else 1,
                        "discipline": discipline.id,
                    })
                for checkpoint in discipline.checkpoints:
                    if (checkpoint.due_on and 0 <= (checkpoint.due_on - today).days <= 3
                            and checkpoint.id not in scores and not checkpoint.is_final):
                        days = (checkpoint.due_on - today).days
                        when = "сегодня" if days == 0 else "завтра" if days == 1 else f"через {days} дн."
                        candidates.append({
                            "rule": "DEADLINE_3D", "key": f"DEADLINE_3D:{checkpoint.id}",
                            "title": f"Дедлайн {when}: {discipline.title}",
                            "text": f"«{checkpoint.title}» — {checkpoint.weight} баллов из 100. Балла пока нет.",
                            "action": {"label": "Открыть дисциплину", "link": f"/study/{discipline.id}"},
                            "priority": 2 if result.level == "green" else 1.5,
                        })
            finals = sorted((d.final_at for d in disciplines if d.final_at), key=lambda x: x)
            if finals and 0 <= (finals[0].astimezone(MOSCOW).date() - today).days <= 14:
                candidates.append({
                    "rule": "SESSION_14D", "key": f"SESSION_14D:{finals[0].date().isoformat()}",
                    "title": "До сессии меньше двух недель",
                    "text": "Проверьте допуск по каждой дисциплине и закройте долги заранее.",
                    "action": {"label": "Открыть успеваемость", "link": "/study"}, "priority": 3,
                })
            stale = list((await db.scalars(
                select(StudentRequest).where(StudentRequest.student_id == student.id, StudentRequest.status == "needs_info")
            )).all())
            for request in stale:
                if now - request.updated_at >= timedelta(hours=48):
                    candidates.append({
                        "rule": "REQ_STALE", "key": f"REQ_STALE:{request.id}",
                        "title": "Деканат ждёт вашего ответа",
                        "text": f"По заявке {request.number} нужны уточнения — без ответа она не движется.",
                        "action": {"label": "Ответить", "link": f"/requests/{request.id}"}, "priority": 0,
                    })
            existing = {
                row.dedup_key: row for row in (await db.scalars(select(Nudge).where(Nudge.student_id == student.id))).all()
            }
            start_of_day = datetime.combine(today, datetime.min.time(), tzinfo=MOSCOW)
            created_today = sum(1 for row in existing.values() if row.created_at >= start_of_day)
            fresh: list[Nudge] = []
            for candidate in sorted(candidates, key=lambda c: c["priority"]):
                if candidate["rule"] in muted or candidate["key"] in existing:
                    continue
                if created_today >= NUDGES_PER_DAY:
                    break
                nudge = Nudge(student_id=student.id, rule_code=candidate["rule"], dedup_key=candidate["key"],
                              title=candidate["title"], text=candidate["text"], action=candidate["action"], created_at=now)
                db.add(nudge)
                fresh.append(nudge)
                created_today += 1
            await db.commit()
            active = list((await db.scalars(
                select(Nudge).where(Nudge.student_id == student.id, Nudge.state.in_(("new", "seen")))
                .order_by(Nudge.created_at.desc())
            )).all())
            email = student.email
        if fresh and self.notify is not None:
            try:
                self.notify(email, [
                    {"event_key": f"nudge:{n.dedup_key}", "kind": "nudge", "title": n.title, "body": n.text,
                     "payload": {"link": n.action.get("link", "/")}}
                    for n in fresh
                ])
            except Exception:
                pass
        return [
            {"id": str(n.id), "rule": n.rule_code, "rule_label": NUDGE_RULES.get(n.rule_code, n.rule_code),
             "title": n.title, "text": n.text, "action": n.action, "state": n.state, "created_at": n.created_at.isoformat()}
            for n in active if n.rule_code not in muted
        ]

    async def update_nudge(self, user: User, nudge_id: uuid.UUID, state: str, mute: bool = False) -> None:
        student = self._student_of(user)
        async with self.database.session() as db:
            nudge = await db.get(Nudge, nudge_id)
            if nudge is None or nudge.student_id != student.id:
                raise not_found("Подсказка не найдена.")
            nudge.state = state
            if mute and await db.get(NudgeMute, (student.id, nudge.rule_code)) is None:
                db.add(NudgeMute(student_id=student.id, rule_code=nudge.rule_code))
            await db.commit()


def _mark_for(total: float) -> str:
    if total >= 85:
        return "отлично"
    if total >= 70:
        return "хорошо"
    if total >= 55:
        return "удовлетворительно"
    return "неудовлетворительно"


def _plural(count: int, one: str, few: str, many: str) -> str:
    mod10, mod100 = count % 10, count % 100
    if mod10 == 1 and mod100 != 11:
        return one
    if 2 <= mod10 <= 4 and not 12 <= mod100 <= 14:
        return few
    return many
