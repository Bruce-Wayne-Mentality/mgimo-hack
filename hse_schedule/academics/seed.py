"""Seed the demo curriculum, classmates, scores and traffic-light history.

Runs after accounts are seeded; skipped entirely when disciplines exist, so
the jury's edits survive restarts (a reset re-creates everything).
"""

from __future__ import annotations

import secrets
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import func, select

from ..accounts.models import Student, StudyGroup, User
from ..accounts.security import hash_password
from ..db import Database, utcnow
from . import curriculum, risk
from .models import Attendance, Checkpoint, Discipline, Grade, GradeChange, PastResult, RiskSnapshot
from .service import moscow_today

MOSCOW = curriculum.MOSCOW


def _at(day: date, hour: int = 15) -> datetime:
    return datetime.combine(day, time(hour, 0), tzinfo=MOSCOW).astimezone(timezone.utc)


async def seed_academics(database: Database, *, now: datetime | None = None) -> dict[str, int]:
    now = now or utcnow()
    today = moscow_today(now)
    created = {"disciplines": 0, "students": 0, "grades": 0}
    async with database.session() as db:
        if await db.scalar(select(func.count()).select_from(Discipline)):
            return created
        groups = {row.code: row for row in (await db.scalars(select(StudyGroup))).all()}
        students = {
            login: student
            for login, student in (await db.execute(select(User.login, Student).join(Student, Student.user_id == User.id))).all()
        }

        # Classmates who cannot sign in (inactive, random password) — for the staff gradebook.
        unusable = hash_password(secrets.token_urlsafe(32))
        background: dict[str, list[tuple[Student, dict]]] = {}
        for group_code in curriculum.DISCIPLINES:
            if group_code not in groups:
                continue
            for row in curriculum.background_students(group_code, 12):
                student = students.get(row["login"])
                if student is None:
                    user = User(login=row["login"], password_hash=unusable, role="student", is_active=False)
                    db.add(user)
                    await db.flush()
                    student = Student(user_id=user.id, full_name=row["full_name"], record_book_no=row["record_book_no"],
                                      group_id=groups[group_code].id, email=row["email"])
                    db.add(student)
                    created["students"] += 1
                background.setdefault(group_code, []).append((student, row))
        await db.flush()

        for group_code, items in curriculum.DISCIPLINES.items():
            group = groups.get(group_code)
            if group is None:
                continue
            for data in items:
                discipline = Discipline(
                    group_id=group.id, semester=curriculum.SEMESTER, code=data["code"], title=data["title"],
                    teacher_name=data["teacher"], control_form=data["form"], credits=data["credits"],
                    admission_threshold=40, final_at=curriculum.final_at(data, today), final_room=data["room"],
                )
                db.add(discipline)
                await db.flush()
                created["disciplines"] += 1
                checkpoints = []
                for row in curriculum.checkpoint_rows(data, today):
                    checkpoint = Checkpoint(discipline_id=discipline.id, **row)
                    db.add(checkpoint)
                    checkpoints.append(checkpoint)
                await db.flush()
                teacher = f"Преподаватель: {data['teacher'].split()[0]} {data['teacher'].split()[1][0]}. {data['teacher'].split()[2][0]}."

                # Test students: exact fractions from the curriculum.
                for login, plan in curriculum.SCORES.items():
                    student = students.get(login)
                    if student is None or student.group_id != group.id or data["code"] not in plan:
                        continue
                    entry = plan[data["code"]]
                    fractions = list(entry["scores"])
                    created["grades"] += _grade(db, student, checkpoints, fractions, teacher)
                    attended, total = entry["attendance"]
                    db.add(Attendance(student_id=student.id, discipline_id=discipline.id, attended=attended, total=total))
                    _backfill(db, discipline, checkpoints, student, fractions, (attended, total), today, now)

                # Classmates: deterministic noise around their «quality».
                for student, row in background.get(group_code, []):
                    rng = __import__("random").Random(f"{row['login']}-{data['code']}")
                    fractions = []
                    for checkpoint in checkpoints:
                        if checkpoint.due_on is None or checkpoint.due_on > today - timedelta(days=1):
                            break
                        if rng.random() < 0.08 * (1.4 - row["quality"]):
                            fractions.append(None)
                        else:
                            fractions.append(max(0.0, min(1.0, rng.gauss(row["quality"], 0.12))))
                    created["grades"] += _grade(db, student, checkpoints, fractions, teacher)
                    total = 16
                    attended = max(6, min(total, round(total * rng.uniform(0.6 + 0.3 * row["quality"], 1.0))))
                    db.add(Attendance(student_id=student.id, discipline_id=discipline.id, attended=attended, total=total))

        # An appeal that changed a score — the change history is visible to the student (FR-GRD-2).
        anna = students.get("student.anna")
        if anna is not None:
            micro = await db.scalar(select(Discipline).where(Discipline.code == "MICRO", Discipline.group_id == anna.group_id))
            if micro is not None:
                await db.flush()
                first = (await db.scalars(select(Checkpoint).where(Checkpoint.discipline_id == micro.id).order_by(Checkpoint.sort))).first()
                grade = await db.scalar(select(Grade).where(Grade.student_id == anna.id, Grade.checkpoint_id == first.id))
                if grade is not None:
                    db.add(GradeChange(student_id=anna.id, checkpoint_id=first.id, old_score=16, new_score=grade.score,
                                       changed_by_name="Деканат: апелляционная комиссия",
                                       reason="Апелляция: пересчитана задача 3", at=_at(first.due_on + timedelta(days=9), 12)))

        for login, rows in curriculum.PAST.items():
            student = students.get(login)
            if student is None:
                continue
            for semester_no, label, title, form, credits, mark in rows:
                db.add(PastResult(student_id=student.id, semester_no=semester_no, semester=label, title=title,
                                  control_form=form, credits=credits, mark=mark, passed=True))
        await db.commit()
    return created


def _grade(db, student, checkpoints, fractions, teacher) -> int:
    count = 0
    for checkpoint, fraction in zip(checkpoints, fractions):
        if fraction is None:
            continue
        score = round(fraction * checkpoint.max_score * 2) / 2
        graded = _at(checkpoint.due_on + timedelta(days=2)) if checkpoint.due_on else utcnow()
        db.add(Grade(student_id=student.id, checkpoint_id=checkpoint.id, score=score, graded_at=graded))
        db.add(GradeChange(student_id=student.id, checkpoint_id=checkpoint.id, old_score=None, new_score=score,
                           changed_by_name=teacher, at=graded))
        count += 1
    return count


def _backfill(db, discipline, checkpoints, student, fractions, attendance, today, now) -> None:
    """Traffic-light history for the trend: how the light looked over the last weeks."""
    last = None
    for offset in (-35, -21, -10, -3, 0):
        day = today + timedelta(days=offset)
        inputs = []
        for index, checkpoint in enumerate(checkpoints):
            fraction = fractions[index] if index < len(fractions) else None
            graded_by = checkpoint.due_on + timedelta(days=2) if checkpoint.due_on else None
            score = None
            if fraction is not None and graded_by is not None and graded_by <= day:
                score = round(fraction * checkpoint.max_score * 2) / 2
            inputs.append(risk.CheckpointInput(checkpoint.weight, checkpoint.max_score, checkpoint.due_on, score,
                                               checkpoint.critical, checkpoint.title))
        attended, total = attendance
        share = max(0.2, (35 + offset) / 35) if offset < 0 else 1
        result = risk.compute(inputs, today=day, threshold=discipline.admission_threshold,
                              attended=round(attended * share), total_lessons=round(total * share))
        if last is None or last != (result.level, round(result.p, 1)):
            at = now if offset == 0 else _at(day, 3)
            db.add(RiskSnapshot(student_id=student.id, discipline_id=discipline.id, level=result.level, p=result.p,
                                w=result.w, pace=result.pace, r=result.r, reasons=list(result.reasons), computed_at=at))
            last = (result.level, round(result.p, 1))
