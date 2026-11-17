"""«Красная кнопка»: submission, two automatic stages + a human, statuses, roles.

Privacy rules (spec, section 6):
- raw attempts live only in the encrypted buffer and are destroyed in the same
  transaction in which the complaint is accepted;
- the registry keeps one final text, sealed with its own key, no edit history;
- texts never reach logs; GigaChat gets a masked copy without obscenity or
  the author's personal data;
- named: the executor sees name and group; confidential: only the curator sees
  the name, the executor sees «Студент #7F3A»; anonymous: nobody does.
- conflict of interest: the subject of a complaint never sees it (404).
"""

from __future__ import annotations

import asyncio
import os
import uuid
from collections.abc import Callable
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select

from ..accounts.models import AuditLog, Student, User
from ..accounts.router import ApiError
from ..db import Database, utcnow
from ..gigachat import GigaChat, GigaChatBlacklisted, GigaChatUnavailable
from ..student_requests.service import add_business_days
from . import stage1, stage2
from .crypto import KeyStore
from ..accounts.policy import can_open_complaint_attachment
from ..attachments import storage
from ..attachments.files import AttachmentError, limits, prepare
from ..attachments.models import ComplaintAttachment
from . import attachments
from .models import (
    Complaint,
    ComplaintAuthor,
    ComplaintCounter,
    ComplaintEvent,
    ComplaintMessage,
    ModerationBuffer,
    ModerationEvent,
)

MOSCOW = ZoneInfo("Europe/Moscow")

TYPE_LABELS = {"unfair": "Несправедливость", "problem": "Проблема", "suggestion": "Предложение", "thanks": "Благодарность"}
CATEGORY_LABELS = {
    "grades": "Оценки и аттестация", "schedule": "Расписание", "teacher_conduct": "Поведение преподавателя",
    "dean_office": "Деканат", "documents": "Документы", "scholarship_payment": "Стипендия и оплата",
    "dormitory": "Общежитие", "infrastructure": "Инфраструктура", "other": "Другое",
}
DEPARTMENTS = {
    "grades": "Учебный офис программы", "schedule": "Учебный офис программы", "teacher_conduct": "Деканат факультета",
    "dean_office": "Деканат факультета", "documents": "Деканат факультета", "scholarship_payment": "Бухгалтерия (демо)",
    "dormitory": "Студгородок (демо)", "infrastructure": "Хозяйственная служба (демо)", "other": "Деканат факультета",
}
STATUS_LABELS = {
    "MODERATION": "На проверке", "NEW": "Принято", "IN_PROGRESS": "В работе", "NEED_INFO": "Нужна информация",
    "ANSWERED": "Есть ответ", "ESCALATED": "Передано выше", "CLOSED": "Закрыто", "WITHDRAWN": "Отозвано",
    "RETURNED": "Возвращено автору",
}
PRIVACY_LABELS = {"named": "От своего имени", "confidential": "Конфиденциально", "anonymous": "Анонимно"}
DESIRED_LABELS = {"review": "Пересмотр решения", "explain": "Объяснение", "fix": "Исправить проблему", "record": "Просто зафиксировать"}
MISSING_LABELS = {"what": "Что именно произошло?", "when": "Когда это было?", "where": "Где это было (дисциплина, аудитория, сервис)?",
                  "desired_outcome": "Чего вы хотите добиться?"}
MODERATION_REASONS = {
    "risk_threat": "Возможная угроза", "risk_self_harm": "Риск для автора", "risk_safety": "Опасность в здании",
    "ai_insult": "ИИ видит оскорбление", "ai_unavailable": "ИИ-проверка не удалась", "ai_blacklist": "Цензор GigaChat",
    "manual_review": "Автор попросил ручную проверку",
    "attachment_unverified": "Вложение не проверено автоматически", "attachment_unsafe": "Во вложении возможный риск",
}
PSYCH_HELP = "Если вам тяжело — психологическая служба (демо): 8-800-000-00-00, круглосуточно. В экстренной ситуации звоните 112."
OPEN = ("NEW", "IN_PROGRESS", "NEED_INFO", "ANSWERED", "ESCALATED")
FORM_FIELDS = ("type", "category", "link_type", "link_id", "link_label", "desired_outcome", "privacy", "attachment_ids")
DAILY_LIMIT = 5
BUFFER_DAYS = 14
TAKE_DAYS, ANSWER_DAYS = 2, 10
AUTO_CLOSE = timedelta(days=7)


def not_found() -> ApiError:
    return ApiError(404, "not_found", "Обращение не найдено.")


class RedButtonService:
    def __init__(self, database: Database, *, keys: KeyStore | None = None, gigachat: GigaChat | None = None,
                 notify: Callable[[str, list[dict]], None] | None = None, clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.keys = keys or KeyStore()
        self.gigachat = gigachat
        self.notify = notify
        self.clock = clock
        self._daily: dict[str, int] = {}
        self._tasks: set[asyncio.Task] = set()
        self._worker: asyncio.Task | None = None

    # ---- helpers ---------------------------------------------------------------

    @staticmethod
    def role(user: User) -> str | None:
        if not user.is_active:
            return None
        return {"admin": "curator", "staff": "executor"}.get(user.role)

    def _overdue(self, c: Complaint) -> bool:
        now = self.clock()
        if c.status == "NEW":
            return now > c.take_due_at
        return c.status in ("IN_PROGRESS", "ESCALATED") and now > c.answer_due_at

    async def _number(self, db, now: datetime) -> str:
        year = now.astimezone(MOSCOW).year
        counter = await db.scalar(select(ComplaintCounter).where(ComplaintCounter.year == year).with_for_update())
        if counter is None:
            counter = ComplaintCounter(year=year, value=0)
            db.add(counter)
        counter.value += 1
        return f"КК-{year}-{counter.value:04d}"

    def _text(self, c: Complaint) -> str | None:
        if not c.body_dek:
            return None
        return self.keys.open(self.keys.unwrap(c.body_dek), c.body_ct, str(c.id))

    def _seal_message(self, c: Complaint, text: str, message_id: uuid.UUID) -> bytes:
        return self.keys.seal(self.keys.unwrap(c.body_dek), text, f"{c.id}|{message_id}")

    def _open_message(self, c: Complaint, m: ComplaintMessage) -> str | None:
        if not c.body_dek:
            return None
        return self.keys.open(self.keys.unwrap(c.body_dek), m.body_ct, f"{c.id}|{m.id}")

    def _event(self, db, c: Complaint, to: str, actor: str) -> None:
        db.add(ComplaintEvent(complaint_id=c.id, from_status=c.status if c.status != to else None, to_status=to,
                              actor_role=actor, at=self.clock()))
        c.status = to
        c.updated_at = self.clock()

    async def _author_email(self, db, c: Complaint) -> str | None:
        if c.privacy == "anonymous":
            return None
        return await db.scalar(select(Student.email).join(ComplaintAuthor, ComplaintAuthor.user_id == Student.user_id)
                               .where(ComplaintAuthor.complaint_id == c.id))

    def _tell(self, email: str | None, c: Complaint, title: str, body: str = "") -> None:
        if not email or self.notify is None:
            return
        try:  # notifications carry no complaint text
            self.notify(email, [{"event_key": f"redbutton:{c.id}:{c.status}:{self.clock().timestamp()}", "kind": "complaint",
                                 "title": f"Обращение {c.number}: {title}", "body": body,
                                 "payload": {"link": f"/complaints/{c.id}"}}])
        except Exception:
            pass

    async def _resolve_link(self, db, user: User, link_type: str | None, link_id: str | None, link_label: str | None):
        """Returns (label, subject_user_id, subject_type) for the optional attachment."""
        if not link_type:
            return None, None, None
        if link_type == "discipline":
            from ..academics.models import Discipline

            try:
                discipline = await db.get(Discipline, uuid.UUID(link_id or ""))
            except ValueError:
                discipline = None
            if discipline is None or discipline.group_id != user.student.group_id:
                raise ApiError(422, "validation_failed", "Дисциплина не найдена.", fields={"link_id": "Выберите дисциплину из списка."})
            return f"Дисциплина «{discipline.title}»", None, "teacher"
        if link_type == "request":
            from ..student_requests.models import StudentRequest

            try:
                request = await db.get(StudentRequest, uuid.UUID(link_id or ""))
            except ValueError:
                request = None
            if request is None or request.student_id != user.student.id:
                raise ApiError(422, "validation_failed", "Заявка не найдена.", fields={"link_id": "Выберите свою заявку."})
            return f"Заявка {request.number} «{request.type.title}»", request.assignee_id, "procedure"
        if link_type in ("room", "lesson"):
            label = (link_label or link_id or "").strip()[:120]
            if not label:
                raise ApiError(422, "validation_failed", "Укажите аудиторию или занятие.")
            prefix = "Аудитория" if link_type == "room" else "Занятие"
            return f"{prefix} {label}", None, "infrastructure" if link_type == "room" else "procedure"
        raise ApiError(422, "validation_failed", "Неизвестная привязка.")

    # ---- submission ------------------------------------------------------------------

    async def submit(self, user: User, form: dict, text: str) -> tuple[int, dict]:
        """Stage 1 now; stage 2 after acceptance. Returns (HTTP status, body)."""
        if user.role != "student" or user.student is None:
            raise ApiError(403, "forbidden", "Обращение подают студенты.")
        text = text.strip()
        now = self.clock()
        author_ref = self.keys.author_ref(user.id)
        session_id = form.get("session_id")
        async with self.database.session() as db:
            if session_id is not None:
                owner = await db.scalar(select(ModerationBuffer.author_ref).where(ModerationBuffer.session_id == session_id).limit(1))
                if owner is not None and owner != author_ref:
                    session_id = None
            session_id = session_id or uuid.uuid4()
            link_label, subject_user_id, subject_type = await self._resolve_link(
                db, user, form.get("link_type"), form.get("link_id"), form.get("link_label"))
        if form.get("attachment_ids"):
            async with self.database.session() as db:
                await self._staged(db, author_ref, form["attachment_ids"])  # 422 before anything is checked
        result = stage1.check(text, desired=form.get("desired_outcome"))
        text_hmac = self.keys.text_hmac(result.normalized)
        async with self.database.session() as db:
            db.add(ModerationEvent(session_id=session_id, stage=1, verdict=result.verdict, scores=result.scores,
                                   flags=result.flags, text_hmac=text_hmac, models=result.models,
                                   latency_ms=result.latency_ms, at=now))
            if result.verdict in ("REJECT_OBSCENE", "ASK_DETAILS"):
                attempts = (await db.scalar(select(func.count()).select_from(ModerationBuffer)
                                            .where(ModerationBuffer.session_id == session_id))) + 1
                key_id, nonce, ct = self.keys.seal_buffer(text, now.astimezone(MOSCOW).date(), str(session_id))
                db.add(ModerationBuffer(session_id=session_id, author_ref=author_ref, seq=attempts, state="returned",
                                        verdict=result.verdict, attempts=attempts, key_id=key_id, nonce=nonce, ct=ct,
                                        # Form choices only: the text itself exists here solely as ciphertext.
                                        form={k: v for k, v in form.items() if k in FORM_FIELDS and v is not None},
                                        created_at=now, expires_at=now + timedelta(days=BUFFER_DAYS)))
                await db.commit()
                body = {"verdict": result.verdict, "session_id": str(session_id), "attempts": attempts}
                if result.verdict == "REJECT_OBSCENE":
                    body["spans"] = [{"start": s.start, "end": s.end} for s in result.spans]
                    body["message"] = "В тексте есть ненормативная лексика. Уберите выделенные фрагменты — суть жалобы сохранится."
                else:
                    body["missing"] = [{"code": code, "question": MISSING_LABELS[code]} for code in result.missing]
                    body["message"] = "Чтобы деканат мог помочь, уточните детали."
                    body["can_manual_review"] = attempts >= 3
                return 200, body
            await db.commit()
        complaint = await self._finalize(user, form, text, session_id, result, link_label, subject_user_id, subject_type)
        body = {"verdict": result.verdict, "complaint": await self.student_view(complaint.id, user)}
        if result.risk == "self_harm":
            body["help"] = PSYCH_HELP
        return 201, body

    def _limit(self, user: User) -> None:
        ref = self.keys.day_salt_ref(user.id, self.clock().astimezone(MOSCOW).date())
        if len(self._daily) > 10_000:
            self._daily.clear()
        if self._daily.get(ref, 0) >= DAILY_LIMIT:
            raise ApiError(429, "rate_limited", f"Не больше {DAILY_LIMIT} обращений в сутки.")
        self._daily[ref] = self._daily.get(ref, 0) + 1

    async def _finalize(self, user: User, form: dict, text: str, session_id, result: stage1.Stage1Result | None,
                        link_label, subject_user_id, subject_type, *, reason: str | None = None) -> Complaint:
        """ACCEPT / ESCALATE / manual review: registry row and buffer deletion in one transaction."""
        self._limit(user)
        now = self.clock()
        category = form.get("category") or "other"
        flags = list(result.flags) if result else []
        if "injection_pattern" in flags:
            flags.append("disputed")
        escalate = result is not None and result.verdict == "ESCALATE"
        status = "MODERATION" if (escalate or reason) else "NEW"
        moderation_reason = reason or (f"risk_{result.risk}" if escalate else None)
        dek, wrapped = self.keys.new_dek()
        author_ref = self.keys.author_ref(user.id)
        async with self.database.session() as db:
            files = await self._staged(db, author_ref, form.get("attachment_ids") or [])
            unsafe = any(f.check_reason == "unsafe" for f in files)
            if any(f.check_status == "unverified" for f in files) and status == "NEW":
                # a file the machine could not vouch for: a person looks first, nothing is rejected silently
                status, moderation_reason = "MODERATION", "attachment_unsafe" if unsafe else "attachment_unverified"
            if unsafe:
                escalate = True
            complaint = Complaint(
                number=await self._number(db, now), type=form.get("type") or "unfair", category=category,
                category_source="student" if form.get("category") else "pending", subject_type=subject_type,
                subject_user_id=subject_user_id, link_type=form.get("link_type"), link_id=form.get("link_id"),
                link_label=link_label, title=f"{TYPE_LABELS.get(form.get('type') or 'unfair')}: {CATEGORY_LABELS[category].lower()}",
                privacy=form.get("privacy") or "confidential", author_ref=self.keys.author_ref(user.id),
                desired_outcome=form.get("desired_outcome"), status=status, priority=1 if escalate else 2,
                department=DEPARTMENTS[category], take_due_at=add_business_days(now, TAKE_DAYS),
                answer_due_at=add_business_days(now, ANSWER_DAYS), created_at=now, updated_at=now, flags=flags,
                moderation_reason=moderation_reason, stage2_state="pending" if self.gigachat else "skipped",
                stage2_next_at=now, body_ct=b"", body_dek=wrapped,
            )
            db.add(complaint)
            await db.flush()
            complaint.body_ct = self.keys.seal(dek, text, str(complaint.id))
            for row in files:
                opened = attachments.open_staged(self.keys, row)
                if opened is None:  # the day key is gone: the file cannot be read any more
                    storage.delete(row.storage_key)
                    await db.delete(row)
                    continue
                name, data = opened
                old_key = row.storage_key
                row.complaint_id = complaint.id
                row.name_ct, row.storage_key = attachments.seal_for_complaint(self.keys, dek, complaint.id, row.id, name, data)
                row.key_id, row.expires_at, row.attached_at = None, None, now
                storage.delete(old_key)
                del data
            if complaint.privacy in ("named", "confidential"):
                db.add(ComplaintAuthor(complaint_id=complaint.id, user_id=user.id))
            db.add(ComplaintEvent(complaint_id=complaint.id, from_status=None, to_status=status, actor_role="system", at=now))
            if session_id is not None:
                await db.execute(update_events_sql(session_id, complaint.id))
                await db.execute(delete(ModerationBuffer).where(ModerationBuffer.session_id == session_id))
            db.add(AuditLog(actor_id=None if complaint.privacy == "anonymous" else user.id, action="complaint.create",
                            object_type="complaint", object_id=str(complaint.id), meta={"privacy": complaint.privacy}))
            await db.commit()
        del dek
        if self.gigachat is not None:
            masked = self._mask(text, user)
            task = asyncio.create_task(self._stage2(complaint.id, masked))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)
        return complaint

    @staticmethod
    def _mask(text: str, user: User | None) -> str:
        names, extra = [], []
        if user is not None and user.student is not None:
            names = [user.student.full_name]
            extra = [user.student.record_book_no, user.student.email, user.student.group.code]
        return stage1.mask_pdn(stage1.mask_obscene(text), names=names, extra=extra)

    async def manual_review(self, user: User, session_id: uuid.UUID) -> dict:
        author_ref = self.keys.author_ref(user.id)
        async with self.database.session() as db:
            row = await db.scalar(select(ModerationBuffer).where(ModerationBuffer.session_id == session_id)
                                  .order_by(ModerationBuffer.seq.desc()).limit(1))
        if row is None or row.author_ref != author_ref:
            raise ApiError(404, "not_found", "Черновик не найден.")
        if row.verdict == "REJECT_OBSCENE":
            raise ApiError(409, "not_allowed", "Текст с ненормативной лексикой нельзя отправить на ручную проверку — уберите её.")
        if row.attempts < 3:
            raise ApiError(409, "not_allowed", "Ручная проверка доступна после трёх попыток уточнить текст.")
        text = self.keys.open_buffer(row.key_id, row.nonce, row.ct, str(session_id))
        if text is None:
            raise ApiError(410, "expired", "Черновик устарел. Напишите обращение заново.")
        async with self.database.session() as db:
            label, subject, subject_type = await self._resolve_link(db, user, row.form.get("link_type"),
                                                                    row.form.get("link_id"), row.form.get("link_label"))
        complaint = await self._finalize(user, row.form, text, session_id, None, label, subject, subject_type,
                                         reason="manual_review")
        return await self.student_view(complaint.id, user)

    # ---- stage 2 -----------------------------------------------------------------------

    async def _stage2(self, complaint_id: uuid.UUID, masked: str | None = None) -> None:
        async with self.database.session() as db:
            c = await db.get(Complaint, complaint_id)
            if c is None or c.stage2_state not in ("pending",) or not c.body_dek:
                return
            if masked is None:
                author = None
                if c.privacy != "anonymous":
                    user_id = await db.scalar(select(ComplaintAuthor.user_id).where(ComplaintAuthor.complaint_id == c.id))
                    author = await db.get(User, user_id) if user_id else None
                masked = self._mask(self._text(c) or "", author)
            context = {"type_label": TYPE_LABELS[c.type],
                       "category_label": CATEGORY_LABELS[c.category] if c.category_source == "student" else None,
                       "link_label": c.link_label}
        verdict, tokens, latency, scores = "STAGE2_OK", 0, 0, {}
        try:
            answer = await self.gigachat.chat_json(stage2.SYSTEM, stage2.user_message(masked, context), stage2.SCHEMA)
            data = stage2.validate(answer.data)
            tokens, latency = answer.tokens, answer.latency_ms
        except GigaChatBlacklisted:
            data, verdict = None, "PENDING_BLACKLIST"
        except (GigaChatUnavailable, ValueError):
            data, verdict = None, "PENDING"
        finally:
            del masked
        now = self.clock()
        async with self.database.session() as db:
            c = await db.get(Complaint, complaint_id)
            if c is None:
                return
            if data is None:
                c.stage2_attempts += 1
                c.stage2_next_at = now + timedelta(minutes=10 * c.stage2_attempts)
                if verdict == "PENDING_BLACKLIST" or c.stage2_attempts >= 3:
                    c.stage2_state = "failed"
                    if c.status == "NEW":
                        c.moderation_reason = "ai_blacklist" if verdict == "PENDING_BLACKLIST" else "ai_unavailable"
                        self._event(db, c, "MODERATION", "system")
            else:
                verdict = self._apply(db, c, data)
                scores = {k: data[k] for k in ("insult", "veiled_obscenity", "risk", "meaningful", "urgency", "confidence")}
            db.add(ModerationEvent(complaint_id=c.id, stage=2, verdict=verdict, scores=scores, flags=list(c.flags),
                                   models={"llm": self.gigachat.model if self.gigachat else "none"},
                                   latency_ms=latency, tokens=tokens, at=now))
            await db.commit()

    def _apply(self, db, c: Complaint, ai: dict) -> str:
        """Post-factum labels: the text is never changed and the complaint never closed by AI."""
        c.ai = {k: ai[k] for k in ("insult", "veiled_obscenity", "risk", "meaningful", "missing", "urgency", "confidence")}
        c.title, c.title_source = ai["title"] or c.title, "ai"
        c.summary = ai["summary"]
        c.subject_type = c.subject_type or ai["subject_type"]
        if c.category_source != "student":
            c.category, c.category_source = ai["category"], "ai"
            c.department = DEPARTMENTS[c.category]
        c.priority = {3: 1, 2: 2, 1: 3}[ai["urgency"]]
        flags = set(c.flags)
        verdict = "ACCEPT"
        if ai["risk"] != "none":
            c.priority = 1
            flags.add(f"risk_{ai['risk']}")
            verdict = "ESCALATE"
            if c.status == "NEW":
                c.moderation_reason = f"risk_{ai['risk']}"
                self._event(db, c, "MODERATION", "system")
        elif (ai["veiled_obscenity"] or ai["insult"] != "none") and ai["confidence"] >= 0.7:
            verdict = "SOFT_REJECT"
            flags.add("ai_insult")
            if c.status == "NEW":
                c.moderation_reason = "ai_insult"
                self._event(db, c, "MODERATION", "system")
        elif "stage1_insult" in flags:
            flags.add("disputed")  # rule 7: the classifier and the LLM disagree
        if not ai["meaningful"]:
            flags.add("unclear")
        c.flags = sorted(flags)
        c.stage2_state = "done"
        return verdict

    # ---- attachments -------------------------------------------------------------------

    async def _staged(self, db, owner_ref: str, ids) -> list:
        """Files a student uploaded for a complaint not submitted yet; all of them, or 422."""
        wanted = list(dict.fromkeys(uuid.UUID(str(i)) for i in ids or []))
        if len(wanted) > limits().max_files:
            raise ApiError(422, "too_many_files", f"Не больше {limits().max_files} файлов в обращении.")
        if not wanted:
            return []
        rows = (await db.scalars(select(ComplaintAttachment).where(
            ComplaintAttachment.id.in_(wanted), ComplaintAttachment.owner_ref == owner_ref,
            ComplaintAttachment.complaint_id.is_(None)))).all()
        if len(rows) != len(wanted):
            raise ApiError(422, "attachments_invalid", "Файл не найден — загрузите его снова.")
        return list(rows)

    async def _claim_for_message(self, db, c: Complaint, message, owner_ref: str, ids, now) -> list:
        wanted = list(dict.fromkeys(uuid.UUID(str(i)) for i in ids or []))
        if len(wanted) > limits().max_files:
            raise ApiError(422, "too_many_files", f"Не больше {limits().max_files} файлов в сообщении.")
        if not wanted:
            return []
        rows = (await db.scalars(select(ComplaintAttachment).where(
            ComplaintAttachment.id.in_(wanted), ComplaintAttachment.complaint_id == c.id,
            ComplaintAttachment.owner_ref == owner_ref, ComplaintAttachment.attached_at.is_(None)))).all()
        if len(rows) != len(wanted):
            raise ApiError(422, "attachments_invalid", "Файл не найден — загрузите его снова.")
        for row in rows:
            row.message_id, row.attached_at, row.expires_at = message.id, now, None
        return list(rows)

    async def upload_attachment(self, user: User, raw: bytes, filename: str | None,
                                complaint_id: uuid.UUID | None = None) -> dict:
        """Check (student files) and seal. Blocked files are not stored at all."""
        try:
            prepared = prepare(raw, filename)
        except AttachmentError as error:
            raise ApiError(error.status, error.code, error.message) from None
        now = self.clock()
        role = self.role(user)
        is_student = user.role == "student" and user.student is not None
        if not is_student and role is None:
            raise not_found()
        owner_ref = self.keys.author_ref(user.id) if is_student else str(user.id)
        async with self.database.session() as db:
            c = None
            if complaint_id is not None:
                c = await db.get(Complaint, complaint_id)
                if c is None or not can_open_complaint_attachment(
                        user, role=None if is_student else role, is_author=is_student and c.author_ref == owner_ref,
                        is_assignee=c.assignee_id == user.id, conflict=c.subject_user_id == user.id):
                    raise not_found()
                if c.status not in ("NEW", "IN_PROGRESS", "NEED_INFO", "ESCALATED"):
                    raise ApiError(409, "not_allowed", "Сейчас прикреплять файлы к этому обращению нельзя.")
            elif not is_student:
                raise not_found()
            pending = (await db.scalars(select(ComplaintAttachment.id).where(
                ComplaintAttachment.owner_ref == owner_ref, ComplaintAttachment.attached_at.is_(None)))).all()
            if len(pending) >= limits().max_files * 2:
                raise ApiError(429, "too_many_files", "Слишком много неотправленных файлов. Отправьте их или уберите лишние.")
        if is_student:
            result = await attachments.check(prepared, self.gigachat, mask=lambda text: self._mask(text, user))
        else:
            result = attachments.CheckResult("skipped")
        if result.status == "blocked":
            return {"id": None, "name": prepared.name, "kind": prepared.kind, "size": len(prepared.data), "url": None,
                    "check": "blocked", "check_label": attachments.STATUS_LABELS["blocked"], "check_message": result.message}
        attachment_id = uuid.uuid4()
        if c is None:
            key_id, name_ct, key = attachments.seal_staged(self.keys, attachment_id, prepared, now.astimezone(MOSCOW).date())
        else:
            key_id = None
            dek = self.keys.unwrap(c.body_dek)
            name_ct, key = attachments.seal_for_complaint(self.keys, dek, c.id, attachment_id, prepared.name, prepared.data)
            del dek
        row = ComplaintAttachment(id=attachment_id, complaint_id=c.id if c else None, owner_ref=owner_ref,
                                  from_role="student" if is_student else ("curator" if role == "curator" else "staff"),
                                  name_ct=name_ct, kind=prepared.kind, mime=prepared.mime, size=len(prepared.data),
                                  storage_key=key, key_id=key_id, check_status=result.status, check_reason=result.reason,
                                  created_at=now, expires_at=now + attachments.STAGED_TTL)
        async with self.database.session() as db:
            db.add(row)
            await db.commit()
        return attachments.payload(row, prepared.name, None)

    async def remove_staged(self, user: User, attachment_id: uuid.UUID) -> None:
        owner_ref = self.keys.author_ref(user.id) if user.role == "student" else str(user.id)
        async with self.database.session() as db:
            row = await db.get(ComplaintAttachment, attachment_id)
            if row is None or row.owner_ref != owner_ref or row.attached_at is not None:
                raise not_found()
            storage.delete(row.storage_key)
            await db.delete(row)
            await db.commit()

    async def open_attachment(self, user: User, complaint_id: uuid.UUID, attachment_id: uuid.UUID) -> tuple[str, str, bytes]:
        """(name, mime, bytes) for the author, the assigned employee or the curator; 404 for anyone else."""
        is_student = user.role == "student" and user.student is not None
        async with self.database.session() as db:
            c = await db.get(Complaint, complaint_id)
            row = await db.get(ComplaintAttachment, attachment_id)
            if c is None or row is None or row.complaint_id != c.id:
                raise not_found()
            owner_ref = self.keys.author_ref(user.id) if is_student else str(user.id)
            allowed = can_open_complaint_attachment(
                user, role=None if is_student else self.role(user), is_author=is_student and c.author_ref == owner_ref,
                is_assignee=c.assignee_id == user.id, conflict=c.subject_user_id == user.id,
                sent=row.attached_at is not None, is_uploader=row.owner_ref == owner_ref)
            if not allowed:
                raise not_found()
            dek = self.keys.unwrap(c.body_dek)
            opened = attachments.open_bound(self.keys, dek, row)
            del dek
            mime = row.mime
        if opened is None:
            raise not_found()
        name, data = opened
        return name, mime, data

    # ---- background work ---------------------------------------------------------------

    def ensure_worker(self) -> None:
        if os.environ.get("REDBUTTON_WORKER", "1") == "0":
            return
        if self._worker is None or self._worker.done():
            try:
                self._worker = asyncio.get_running_loop().create_task(self._loop())
            except RuntimeError:
                self._worker = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                pass  # never log texts; a failed tick is retried next minute
            await asyncio.sleep(60)

    async def tick(self) -> dict:
        """pending-worker + auto-close + purger."""
        now = self.clock()
        done = {"stage2": 0, "closed": 0, "purged": 0, "keys": 0}
        async with self.database.session() as db:
            pending = list((await db.scalars(select(Complaint.id).where(
                Complaint.stage2_state == "pending", Complaint.stage2_next_at <= now))).all())
            for c in (await db.scalars(select(Complaint).where(
                    Complaint.status == "ANSWERED", Complaint.answered_at < now - AUTO_CLOSE))).all():
                self._event(db, c, "CLOSED", "system")
                c.closed_at = now
                done["closed"] += 1
            result = await db.execute(delete(ModerationBuffer).where(ModerationBuffer.expires_at < now))
            done["purged"] = result.rowcount or 0
            for row in (await db.scalars(select(ComplaintAttachment).where(
                    ComplaintAttachment.attached_at.is_(None), ComplaintAttachment.expires_at < now))).all():
                storage.delete(row.storage_key)
                await db.delete(row)
                done["purged"] += 1
            await db.commit()
        if self.gigachat is not None:
            for complaint_id in pending[:5]:
                await self._stage2(complaint_id)
                done["stage2"] += 1
        done["keys"] = self.keys.purge_day_keys(now.astimezone(MOSCOW).date())
        return done

    # ---- student -----------------------------------------------------------------------

    async def _own(self, db, user: User, complaint_id: uuid.UUID) -> Complaint:
        c = await db.get(Complaint, complaint_id)
        if c is None or c.author_ref != self.keys.author_ref(user.id):
            raise not_found()
        return c

    def _base(self, c: Complaint) -> dict:
        return {
            "id": str(c.id), "number": c.number, "type": c.type, "type_label": TYPE_LABELS[c.type],
            "category": c.category, "category_label": CATEGORY_LABELS[c.category], "category_source": c.category_source,
            "link_label": c.link_label, "title": c.title, "title_source": c.title_source,
            "privacy": c.privacy, "privacy_label": PRIVACY_LABELS[c.privacy], "status": c.status,
            "status_label": STATUS_LABELS[c.status], "department": c.department, "priority": c.priority,
            "desired_outcome": c.desired_outcome, "desired_label": DESIRED_LABELS.get(c.desired_outcome or ""),
            "created_at": c.created_at.isoformat(), "updated_at": c.updated_at.isoformat(),
            "take_due_at": c.take_due_at.isoformat(), "answer_due_at": c.answer_due_at.isoformat(),
            "closed_at": c.closed_at.isoformat() if c.closed_at else None, "overdue": self._overdue(c),
            "escalated": c.escalated, "resolved_by_student": c.resolved_by_student,
        }

    async def _files(self, db, c: Complaint, base: str) -> tuple[list[dict], dict]:
        """Sent files: those of the complaint itself and those of each message (names decrypted here)."""
        rows = (await db.scalars(select(ComplaintAttachment).where(
            ComplaintAttachment.complaint_id == c.id, ComplaintAttachment.attached_at.is_not(None))
            .order_by(ComplaintAttachment.created_at))).all()
        dek = self.keys.unwrap(c.body_dek) if c.body_dek and rows else None
        own, per_message = [], {}
        for row in rows:
            item = attachments.payload(row, attachments.open_name(self.keys, dek, row), f"{base}/{c.id}/attachments/{row.id}")
            (per_message.setdefault(row.message_id, []) if row.message_id else own).append(item)
        return own, per_message

    async def _details(self, db, c: Complaint, base: str = "/api/complaints") -> tuple[list[dict], list[dict]]:
        own_files, message_files = await self._files(db, c, base)
        messages = list((await db.scalars(select(ComplaintMessage).where(ComplaintMessage.complaint_id == c.id)
                                          .order_by(ComplaintMessage.created_at))).all())
        events = list((await db.scalars(select(ComplaintEvent).where(ComplaintEvent.complaint_id == c.id)
                                        .order_by(ComplaintEvent.at))).all())
        return (
            [{"id": str(m.id), "from_role": m.from_role, "author": m.author_name if m.from_role != "student" else None,
              "kind": m.kind, "body": self._open_message(c, m), "at": m.created_at.isoformat(),
              "attachments": message_files.get(m.id, [])} for m in messages]
            + ([{"id": f"{c.id}-files", "from_role": "student", "author": None, "kind": "files", "body": "",
                 "at": c.created_at.isoformat(), "attachments": own_files}] if own_files else []),
            [{"to": e.to_status, "label": STATUS_LABELS[e.to_status], "at": e.at.isoformat(), "by": e.actor_role} for e in events],
        )

    async def student_view(self, complaint_id: uuid.UUID, user: User) -> dict:
        async with self.database.session() as db:
            c = await self._own(db, user, complaint_id)
            messages, events = await self._details(db, c)
        data = self._base(c)
        data.update({
            "text": self._text(c), "messages": messages, "events": events, "return_comment": c.return_comment,
            "can_withdraw": c.status == "NEW",
            "can_message": c.status in ("NEW", "IN_PROGRESS", "NEED_INFO", "ESCALATED"),
            "can_feedback": c.status == "ANSWERED",
            "can_escalate": c.status == "ANSWERED" and not c.escalated,
        })
        return data

    async def list_own(self, user: User) -> list[dict]:
        if user.role != "student":
            return []
        async with self.database.session() as db:
            rows = list((await db.scalars(select(Complaint).where(Complaint.author_ref == self.keys.author_ref(user.id))
                                          .order_by(Complaint.created_at.desc()))).all())
        return [self._base(c) | {"waiting_for_me": c.status in ("NEED_INFO", "ANSWERED")} for c in rows]

    async def message(self, user: User, complaint_id: uuid.UUID, text: str, attachment_ids: list = ()) -> dict:
        text = text.strip()
        if not text and not attachment_ids:
            raise ApiError(422, "validation_failed", "Напишите сообщение или прикрепите файл.")
        check = stage1.check(text) if len(text) >= 3 else None
        if check is not None and check.verdict == "REJECT_OBSCENE":
            raise ApiError(422, "obscene", "Уберите ненормативную лексику из сообщения.",
                           fields={"spans": [[s.start, s.end] for s in check.spans]})
        now = self.clock()
        async with self.database.session() as db:
            c = await self._own(db, user, complaint_id)
            if c.status not in ("NEW", "IN_PROGRESS", "NEED_INFO", "ESCALATED"):
                raise ApiError(409, "not_allowed", "Сейчас писать в это обращение нельзя.")
            message = ComplaintMessage(complaint_id=c.id, from_role="student", kind="message", created_at=now, body_ct=b"")
            message.id = uuid.uuid4()
            message.body_ct = self._seal_message(c, text, message.id)
            db.add(message)
            await db.flush()
            files = await self._claim_for_message(db, c, message, self.keys.author_ref(user.id), attachment_ids, now)
            if any(f.check_status == "unverified" for f in files):
                c.flags = sorted(set(c.flags) | {"attachment_unverified"})
            if c.status == "NEED_INFO":
                if c.paused_at:  # SLA hours stand still while the deanery waits for the student
                    c.answer_due_at += now - c.paused_at
                    c.paused_at = None
                self._event(db, c, "IN_PROGRESS", "student")
            c.updated_at = now
            await db.commit()
        return await self.student_view(complaint_id, user)

    async def feedback(self, user: User, complaint_id: uuid.UUID, resolved: bool, comment: str | None) -> dict:
        now = self.clock()
        comment = (comment or "").strip()
        async with self.database.session() as db:
            c = await self._own(db, user, complaint_id)
            if c.status != "ANSWERED":
                raise ApiError(409, "not_allowed", "Оценить можно только обращение с ответом.")
            if resolved:
                c.resolved_by_student = True
                c.closed_at = now
                self._event(db, c, "CLOSED", "student")
            else:
                if c.escalated:
                    raise ApiError(409, "not_allowed", "Обращение уже передавали выше: эскалация возможна один раз.")
                if len(comment) < 10:
                    raise ApiError(422, "validation_failed", "Объясните, с чем вы не согласны.", fields={"comment": "От 10 символов."})
                check = stage1.check(comment)
                if check.verdict == "REJECT_OBSCENE":
                    raise ApiError(422, "obscene", "Уберите ненормативную лексику из комментария.")
                message = ComplaintMessage(complaint_id=c.id, from_role="student", kind="feedback", created_at=now, body_ct=b"")
                message.id = uuid.uuid4()
                message.body_ct = self._seal_message(c, comment, message.id)
                db.add(message)
                c.escalated = True
                c.resolved_by_student = False
                c.assignee_id = None  # the next level: the curator / student ombudsman
                c.answer_due_at = add_business_days(now, ANSWER_DAYS)
                self._event(db, c, "ESCALATED", "student")
            await db.commit()
        return await self.student_view(complaint_id, user)

    async def withdraw(self, user: User, complaint_id: uuid.UUID) -> None:
        async with self.database.session() as db:
            c = await self._own(db, user, complaint_id)
            if c.status != "NEW":
                raise ApiError(409, "not_allowed", "Отозвать можно только пока обращение не взяли в работу.")
            # The text is deleted at once: drop the ciphertext and its key.
            c.body_ct, c.body_dek = b"", None
            await db.execute(delete(ComplaintMessage).where(ComplaintMessage.complaint_id == c.id))
            c.closed_at = self.clock()
            self._event(db, c, "WITHDRAWN", "student")
            await db.commit()

    # ---- staff -------------------------------------------------------------------------

    def _visible(self, c: Complaint, user: User, role: str) -> bool:
        if c.subject_user_id is not None and c.subject_user_id == user.id:
            return False  # conflict of interest
        if role == "curator":
            return True
        return c.status not in ("MODERATION", "RETURNED", "WITHDRAWN")

    async def _author_label(self, db, c: Complaint, role: str) -> str:
        if c.privacy == "anonymous":
            return "Аноним"
        if c.privacy == "confidential" and role != "curator":
            return self.keys.pseudonym(c.id)
        row = (await db.execute(select(Student.full_name, Student.group_id).join(
            ComplaintAuthor, ComplaintAuthor.user_id == Student.user_id).where(ComplaintAuthor.complaint_id == c.id))).first()
        if row is None:
            return "Студент"
        from ..accounts.models import StudyGroup

        group = await db.get(StudyGroup, row.group_id)
        return f"{row.full_name}, {group.code}" if group else row.full_name

    async def _staff_complaint(self, db, user: User, complaint_id: uuid.UUID) -> tuple[Complaint, str]:
        role = self.role(user)
        if role is None:
            raise not_found()
        c = await db.get(Complaint, complaint_id)
        if c is None or not self._visible(c, user, role):
            raise not_found()
        return c, role

    async def queue(self, user: User, *, status: str | None = None, category: str | None = None) -> dict:
        role = self.role(user)
        if role is None:
            raise ApiError(403, "forbidden", "Раздел для сотрудников.")
        async with self.database.session() as db:
            rows = [c for c in (await db.scalars(select(Complaint))).all() if self._visible(c, user, role)]
            items = []
            for c in rows:
                if status == "open" and c.status not in OPEN:
                    continue
                if status and status != "open" and c.status != status:
                    continue
                if category and c.category != category:
                    continue
                items.append(self._base(c) | {"author": await self._author_label(db, c, role), "flags": c.flags,
                                              "summary": c.summary, "moderation_reason": c.moderation_reason})
        rank = {"MODERATION": 0, "ESCALATED": 1, "NEW": 2, "IN_PROGRESS": 3, "NEED_INFO": 4, "ANSWERED": 5}
        items.sort(key=lambda i: (not i["overdue"], rank.get(i["status"], 9), i["priority"], i["answer_due_at"]))
        counts = {s: sum(1 for c in rows if c.status == s) for s in STATUS_LABELS}
        return {"items": items, "counts": counts, "role": role}

    async def staff_view(self, user: User, complaint_id: uuid.UUID) -> dict:
        async with self.database.session() as db:
            c, role = await self._staff_complaint(db, user, complaint_id)
            messages, events = await self._details(db, c, "/api/staff/complaints")
            author = await self._author_label(db, c, role)
            moderation = list((await db.scalars(select(ModerationEvent).where(ModerationEvent.complaint_id == c.id)
                                                .order_by(ModerationEvent.at))).all())
            assignee = await db.get(User, c.assignee_id) if c.assignee_id else None
            staff = list((await db.scalars(select(User).where(User.role.in_(("staff", "admin")), User.is_active.is_(True)))).all()) \
                if role == "curator" else []
            db.add(AuditLog(actor_id=user.id, action="complaint.view", object_type="complaint", object_id=str(c.id)))
            await db.commit()
        actions = []
        if c.status == "MODERATION" and role == "curator":
            actions += [{"action": "accept", "label": "Принять"}, {"action": "return", "label": "Вернуть автору", "text": True}]
        if c.status == "NEW" or (c.status == "ESCALATED" and role == "curator"):
            actions.append({"action": "take", "label": "Взять в работу"})
        if c.status == "IN_PROGRESS":
            actions += [{"action": "need_info", "label": "Запросить информацию", "text": True},
                        {"action": "answer", "label": "Ответить", "text": True}]
        if c.status in ("NEW", "IN_PROGRESS", "NEED_INFO", "ESCALATED"):
            actions.append({"action": "message", "label": "Написать", "text": True})
        data = self._base(c)
        data.update({
            "text": self._text(c), "messages": messages, "events": events, "author": author, "role": role,
            "summary": c.summary, "ai": c.ai, "flags": c.flags, "moderation_reason": c.moderation_reason,
            "moderation_reason_label": MODERATION_REASONS.get(c.moderation_reason or ""), "return_comment": c.return_comment,
            "stage2_state": c.stage2_state, "assignee": assignee.display_name if assignee else None,
            "moderation": [{"stage": m.stage, "verdict": m.verdict, "scores": m.scores, "flags": m.flags,
                            "models": m.models, "latency_ms": m.latency_ms, "at": m.at.isoformat()} for m in moderation],
            "actions": actions,
            "assignees": [{"id": str(u.id), "name": u.display_name} for u in staff if u.id != c.subject_user_id],
        })
        return data

    async def act(self, user: User, complaint_id: uuid.UUID, action: str, text: str | None, attachment_ids: list = ()) -> dict:
        text = (text or "").strip()
        now = self.clock()
        async with self.database.session() as db:
            c, role = await self._staff_complaint(db, user, complaint_id)
            needs_text = action in ("need_info", "answer", "message", "return")
            if needs_text and len(text) < 3:
                raise ApiError(422, "validation_failed", "Напишите текст.", fields={"text": "Напишите текст."})
            title = None
            if action == "accept" and role == "curator" and c.status == "MODERATION":
                c.moderation_reason = None
                self._event(db, c, "NEW", "curator")
                title = "принято после проверки"
            elif action == "return" and role == "curator" and c.status == "MODERATION":
                c.return_comment = text
                c.closed_at = now
                self._event(db, c, "RETURNED", "curator")
                title = "возвращено с комментарием"
            elif action == "take" and (c.status == "NEW" or (c.status == "ESCALATED" and role == "curator")):
                c.assignee_id, c.taken_at = user.id, now
                self._event(db, c, "IN_PROGRESS", role)
                title = "взято в работу"
            elif action in ("need_info", "answer") and c.status == "IN_PROGRESS":
                self._add_message(db, c, role, user, text, action, now)
                if action == "need_info":
                    c.paused_at = now
                    self._event(db, c, "NEED_INFO", role)
                    title = "нужна информация"
                else:
                    c.answered_at = now
                    self._event(db, c, "ANSWERED", role)
                    title = "есть ответ"
            elif action == "message" and c.status in ("NEW", "IN_PROGRESS", "NEED_INFO", "ESCALATED"):
                message = self._add_message(db, c, role, user, text, "message", now)
                await db.flush()
                await self._claim_for_message(db, c, message, str(user.id), attachment_ids, now)
                title = "новое сообщение"
            else:
                raise ApiError(409, "invalid_transition", f"Из статуса «{STATUS_LABELS[c.status]}» так нельзя.")
            db.add(AuditLog(actor_id=user.id, action=f"complaint.{action}", object_type="complaint", object_id=str(c.id)))
            email = await self._author_email(db, c)
            await db.commit()
        self._tell(email, c, title)
        return await self.staff_view(user, complaint_id)

    def _add_message(self, db, c: Complaint, role: str, user: User, text: str, kind: str, now: datetime) -> None:
        message = ComplaintMessage(complaint_id=c.id, from_role="curator" if role == "curator" else "staff",
                                   author_name=user.display_name, kind=kind, created_at=now, body_ct=b"")
        message.id = uuid.uuid4()
        message.body_ct = self._seal_message(c, text, message.id)
        db.add(message)
        c.updated_at = now
        return message

    async def assign(self, user: User, complaint_id: uuid.UUID, assignee_id: uuid.UUID) -> dict:
        async with self.database.session() as db:
            c, role = await self._staff_complaint(db, user, complaint_id)
            if role != "curator":
                raise ApiError(403, "forbidden", "Назначает куратор.")
            target = await db.get(User, assignee_id)
            if target is None or target.role not in ("staff", "admin") or target.id == c.subject_user_id:
                raise ApiError(422, "validation_failed", "Этого сотрудника назначить нельзя.")
            c.assignee_id = target.id
            db.add(AuditLog(actor_id=user.id, action="complaint.assign", object_type="complaint", object_id=str(c.id)))
            await db.commit()
        return await self.staff_view(user, complaint_id)


def update_events_sql(session_id, complaint_id):
    from sqlalchemy import update

    return update(ModerationEvent).where(ModerationEvent.session_id == session_id).values(complaint_id=complaint_id)


def today(now: datetime) -> date:
    return now.astimezone(MOSCOW).date()
