"""Demo complaints for the jury scenarios (spec, section 5). All texts are fictional."""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import func, select

from ..accounts.models import Student, User
from ..db import Database, utcnow
from ..student_requests.service import add_business_days
from .crypto import KeyStore
from .models import Complaint, ComplaintAuthor, ComplaintCounter, ComplaintEvent, ComplaintMessage, ModerationEvent
from .service import ANSWER_DAYS, DEPARTMENTS, MOSCOW, TAKE_DAYS


async def seed_redbutton(database: Database, keys: KeyStore | None = None, *, now: datetime | None = None) -> int:
    keys = keys or KeyStore()
    now = now or utcnow()
    async with database.session() as db:
        if await db.scalar(select(func.count()).select_from(Complaint)):
            return 0
        users = {u.login: u for u in (await db.scalars(select(User))).all()}
        students = {row.user_id: row for row in (await db.scalars(select(Student))).all()}
        if not {"student.anna", "student.boris", "student.vera", "staff.deanery", "admin.demo"} <= users.keys():
            return 0
        from ..academics.models import Discipline
        from ..student_requests.models import StudentRequest

        boris, anna, vera = users["student.boris"], users["student.anna"], users["student.vera"]
        staff, curator = users["staff.deanery"], users["admin.demo"]
        corpfin = await db.scalar(select(Discipline).where(Discipline.code == "CORPFIN"))
        intern = await db.scalar(select(StudentRequest).where(StudentRequest.student_id == students[anna.id].id,
                                                              StudentRequest.status == "in_review"))
        year = now.astimezone(MOSCOW).year
        counter = ComplaintCounter(year=year, value=0)
        db.add(counter)

        def make(author: User, *, privacy, type_, category, text, status, created, title, summary, link=None,
                 subject=None, ai=None, flags=(), reason=None, steps=(), messages=(), priority=2) -> Complaint:
            counter.value += 1
            dek, wrapped = keys.new_dek()
            c = Complaint(
                id=uuid.uuid4(), number=f"КК-{year}-{counter.value:04d}", type=type_, category=category,
                category_source="student", subject_type=(ai or {}).get("subject_type", "teacher"),
                subject_user_id=subject, link_type=link[0] if link else None, link_id=link[1] if link else None,
                link_label=link[2] if link else None, title=title, title_source="ai", summary=summary, privacy=privacy,
                author_ref=keys.author_ref(author.id), status="NEW", priority=priority, department=DEPARTMENTS[category],
                take_due_at=add_business_days(created, TAKE_DAYS), answer_due_at=add_business_days(created, ANSWER_DAYS),
                created_at=created, updated_at=created, flags=list(flags), ai=ai or {}, moderation_reason=reason,
                stage2_state="done", stage2_attempts=0, body_ct=b"", body_dek=wrapped,
            )
            c.body_ct = keys.seal(dek, text, str(c.id))
            db.add(c)
            if privacy != "anonymous":
                db.add(ComplaintAuthor(complaint_id=c.id, user_id=author.id))
            db.add(ComplaintEvent(complaint_id=c.id, from_status=None, to_status="NEW" if not reason else "MODERATION",
                                  actor_role="system", at=created))
            db.add(ModerationEvent(complaint_id=c.id, stage=1, verdict="ACCEPT", scores={}, flags=list(flags),
                                   models={"dictionary": "demo"}, at=created))
            db.add(ModerationEvent(complaint_id=c.id, stage=2, verdict="SOFT_REJECT" if reason else "ACCEPT",
                                   scores={k: v for k, v in (ai or {}).items() if k in ("insult", "risk", "urgency", "confidence")},
                                   flags=list(flags), models={"llm": "GigaChat-2 (демо-метка)"}, at=created))
            status_now = "MODERATION" if reason else "NEW"
            for to, offset, actor in steps:
                db.add(ComplaintEvent(complaint_id=c.id, from_status=status_now, to_status=to, actor_role=actor, at=created + offset))
                status_now = to
                if to == "IN_PROGRESS":
                    c.taken_at, c.assignee_id = created + offset, (curator.id if actor == "curator" else staff.id)
                if to == "ANSWERED":
                    c.answered_at = created + offset
                if to == "CLOSED":
                    c.closed_at, c.resolved_by_student = created + offset, True
            c.status = status_now
            for role, who, kind, body, offset in messages:
                message = ComplaintMessage(id=uuid.uuid4(), complaint_id=c.id, from_role=role, author_name=who, kind=kind,
                                           created_at=created + offset, body_ct=b"")
                message.body_ct = keys.seal(dek, body, f"{c.id}|{message.id}")
                db.add(message)
            return c

        ai_ok = {"insult": "none", "veiled_obscenity": False, "risk": "none", "meaningful": True, "missing": [],
                 "urgency": 2, "confidence": 0.9, "subject_type": "teacher"}
        make(boris, privacy="named", type_="unfair", category="grades",
             text="За контрольную работу 2 по корпоративным финансам мне поставили 12 из 20 без комментариев. "
                  "Решение второй задачи совпадает с разбором на семинаре в четверг. Прошу перепроверить работу и показать критерии.",
             status="IN_PROGRESS", created=now - timedelta(days=3),
             title="Снижен балл за контрольную без комментариев", summary="Студент просит перепроверить контрольную по корпоративным финансам и показать критерии оценивания.",
             link=("discipline", str(corpfin.id) if corpfin else "", "Дисциплина «Корпоративные финансы»"), ai=ai_ok,
             steps=[("IN_PROGRESS", timedelta(hours=20), "staff")],
             messages=[("staff", staff.display_name, "message", "Запросили работу и критерии у кафедры. Ответим до конца недели.", timedelta(hours=21))])
        make(anna, privacy="confidential", type_="problem", category="documents",
             text="Справку для стажировки обещали за два рабочих дня, но заявка висит в статусе «В работе», а работодатель ждёт "
                  "документ к пятнице. Прошу ускорить оформление или объяснить, что не так с заявкой.",
             status="NEW", created=now - timedelta(hours=6),
             title="Задержка справки для стажировки", summary="Студентка просит ускорить оформление справки для стажировки, срок у работодателя — пятница.",
             link=("request", str(intern.id) if intern else "", f"Заявка {intern.number} «Справка для стажировки или практики»" if intern else "Заявка"),
             subject=intern.assignee_id if intern else staff.id, ai=ai_ok | {"subject_type": "procedure"})
        make(vera, privacy="anonymous", type_="unfair", category="teacher_conduct",
             text="На консультации перед зачётом по дискретной математике преподаватель сказал, что без покупки его пособия "
                  "к зачёту не допустит. В программе дисциплины такого условия нет. Прошу разобраться и подтвердить, что это не требование.",
             status="ANSWERED", created=now - timedelta(days=4),
             title="Покупка пособия как условие допуска", summary="Сообщение о требовании купить учебное пособие для допуска к зачёту, не предусмотренном программой.",
             ai=ai_ok,
             steps=[("IN_PROGRESS", timedelta(hours=10), "curator"), ("ANSWERED", timedelta(days=2), "curator")],
             messages=[("curator", curator.display_name, "answer",
                        "Проверили программу дисциплины: покупка пособия не может быть условием допуска. Кафедре направлено письмо, "
                        "преподаватель подтвердил, что допуск получают все, кто сдал контрольные точки.", timedelta(days=2))])
        make(boris, privacy="confidential", type_="unfair", category="teacher_conduct",
             text="Преподаватель маркетинга — полное ничтожество, на семинаре в пятницу высмеял мой доклад при всей группе. "
                  "Хочу, чтобы деканат поговорил с ним о корректном поведении.",
             status="MODERATION", created=now - timedelta(hours=2), reason="ai_insult", flags=("ai_insult",),
             title="Жалоба на поведение преподавателя на семинаре", summary="Студент сообщает, что преподаватель высмеял его доклад при группе, и просит деканат вмешаться.",
             ai=ai_ok | {"insult": "person", "confidence": 0.86})
        make(anna, privacy="named", type_="thanks", category="dean_office",
             text="Спасибо специалисту деканата за быструю помощь с переводом на индивидуальный график в прошлом месяце: "
                  "всё решили за два дня и без визита в деканат. Предлагаю отметить её работу.",
             status="CLOSED", created=now - timedelta(days=12), priority=3,
             title="Благодарность специалисту деканата", summary="Студентка благодарит за быстрое оформление индивидуального графика.",
             ai=ai_ok | {"urgency": 1, "subject_type": "department"},
             steps=[("IN_PROGRESS", timedelta(hours=5), "staff"), ("ANSWERED", timedelta(days=1), "staff"), ("CLOSED", timedelta(days=2), "student")],
             messages=[("staff", staff.display_name, "answer", "Спасибо! Передали благодарность руководству факультета.", timedelta(days=1))])
        await db.commit()
        return counter.value
