"""K2: issue, download, verify and revoke documents of ready requests.

- public_id: 16 random characters; the QR link is /verify/<public_id>.<link_sig>
  where link_sig = HMAC-SHA256(key, "link|public_id|issued_at"), shortened.
- signature (stored) = HMAC-SHA256(key, "public_id|issued_at|sha256(pdf)").
- The verify page shows the minimum: type, number, date, initials, status.
  A bad signature and a missing document get the same «Не найдено».
- Only the owner and staff who may see the request can download the PDF.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import string
import uuid
from collections.abc import Callable
from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select

from ..accounts.models import AuditLog, User
from ..accounts.router import ApiError
from ..db import Database, utcnow
from ..student_requests import policy as request_policy
from ..student_requests.catalog import display_payload
from ..student_requests.models import StudentRequest
from .models import Document
from .pdf import DocumentContent, render

MOSCOW = ZoneInfo("Europe/Moscow")
ALPHABET = string.ascii_letters + string.digits
FORMS = {"full_time": "очная", "part_time": "очно-заочная", "distance": "заочная"}
FORMS_DATIVE = {"full_time": "очной", "part_time": "очно-заочной", "distance": "заочной"}

TITLES = {
    "CERT_STUDY": "Справка с места учёбы",
    "TRANSCRIPT": "Академическая справка (выписка)",
    "CERT_INTERN": "Справка для места стажировки",
    "CERT_MIL": "Справка для военного комиссариата",
    "RETAKE": "Направление на пересдачу",
    "TRANSFER": "Уведомление о решении по переводу",
    "ACAD_LEAVE": "Уведомление о решении по академическому отпуску",
    "AID": "Уведомление о решении по материальной помощи",
}


def initials(full_name: str) -> str:
    """First-name and surname initials only («А. М.»), the minimum for the public check page.

    Test accounts are stored as «Имя Отчество Фамилия», classmates as «Фамилия Имя».
    """
    parts = full_name.split()
    if len(parts) == 3:
        return f"{parts[0][0]}. {parts[2][0]}."
    if len(parts) == 2:
        return f"{parts[1][0]}. {parts[0][0]}."
    return f"{full_name[:1]}."


class DocumentService:
    def __init__(self, database: Database, secret: bytes, *, base_url: str | None = None,
                 clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.key = hmac.new(secret, b"documents-v1", hashlib.sha256).digest()
        self.base_url = base_url.rstrip("/") if base_url else None
        self.clock = clock

    # ---- signatures ------------------------------------------------------

    def _mac(self, message: str) -> str:
        return hmac.new(self.key, message.encode("utf-8"), hashlib.sha256).hexdigest()

    def link_sig(self, public_id: str, issued_at: datetime) -> str:
        raw = hmac.new(self.key, f"link|{public_id}|{issued_at.isoformat()}".encode(), hashlib.sha256).digest()
        return base64.urlsafe_b64encode(raw[:16]).decode().rstrip("=")

    def token(self, document: Document) -> str:
        return f"{document.public_id}.{self.link_sig(document.public_id, document.issued_at)}"

    def verify_url(self, document: Document, base_url: str) -> str:
        return f"{(self.base_url or base_url).rstrip('/')}/verify/{self.token(document)}"

    # ---- access ------------------------------------------------------------

    async def _request(self, db, user: User, request_id: uuid.UUID) -> StudentRequest:
        request = await db.get(StudentRequest, request_id)
        if request is None or not request_policy.can_view_request(user, request):
            raise ApiError(404, "not_found", "Заявка не найдена.")
        return request

    async def ensure(self, user: User, request_id: uuid.UUID, base_url: str) -> Document:
        """The document of a ready request; issued on first access."""
        async with self.database.session() as db:
            request = await self._request(db, user, request_id)
            if request.status != "ready":
                raise ApiError(409, "not_ready", "Документ появится, когда заявка будет готова.")
            document = await db.scalar(select(Document).where(Document.request_id == request.id))
            if document is not None:
                return document
            document = await self._issue(db, request, base_url)
            db.add(AuditLog(actor_id=user.id, action="document.issue", object_type="document", object_id=str(document.id)))
            await db.commit()
            return document

    async def _issue(self, db, request: StudentRequest, base_url: str) -> Document:
        from ..academics.models import PastResult

        now = self.clock().replace(microsecond=0)
        student = request.student
        group = student.group
        public_id = "".join(secrets.choice(ALPHABET) for _ in range(16))
        document = Document(
            request_id=request.id, student_id=student.id, public_id=public_id,
            title=TITLES.get(request.type.code, request.type.title), number=request.number,
            holder_initials=initials(student.full_name), issued_at=now, sha256="", signature="", pdf=b"",
        )
        url = self.verify_url(document, base_url)
        local = now.astimezone(MOSCOW)
        issued_on = local.strftime("%d.%m.%Y")
        fields = {row["name"]: row["value"] for row in display_payload(request.type.fields, request.payload)}
        facts = [
            ("ФИО", student.full_name),
            ("Номер зачётной книжки", student.record_book_no),
            ("Факультет", group.faculty.title),
            ("Направление", f"{group.program_code} {group.program_title}"),
            ("Курс и группа", f"{group.course} курс, группа {group.code}"),
            ("Форма обучения", FORMS.get(student.study_form, student.study_form)),
        ]
        paragraphs: list[str] = []
        table = None
        table_title = None
        notes: list[str] = []
        code = request.type.code
        if code == "CERT_STUDY":
            paragraphs.append(
                f"Настоящая справка подтверждает, что <b>{student.full_name}</b> обучается в вымышленном вузе "
                f"«Цифровой деканат» на {group.course} курсе по {FORMS_DATIVE.get(student.study_form, 'очной')} форме обучения."
            )
            destination = fields.get("destination", "по месту требования")
            destination = destination[:1].lower() + destination[1:] if destination[1:2].islower() else destination
            paragraphs.append(f"Справка выдана для предъявления: {destination}. "
                              f"Количество экземпляров: {fields.get('copies', '1')}.")
        elif code == "TRANSCRIPT":
            paragraphs.append(f"Выписка дисциплин и оценок студента <b>{student.full_name}</b> "
                              f"по закрытым семестрам. Язык документа: {fields.get('language', 'Русский')}.")
            rows = list((await db.scalars(
                select(PastResult).where(PastResult.student_id == student.id).order_by(PastResult.semester_no, PastResult.title)
            )).all())
            marks = {5: "отлично", 4: "хорошо", 3: "удовлетворительно", 2: "неудовлетворительно"}
            if rows:
                table_title = "Результаты"
                table = [["Дисциплина", "Семестр", "Оценка"]] + [
                    [row.title, row.semester, marks.get(row.mark, "зачтено") if row.mark else "зачтено"] for row in rows
                ]
                graded = [row.mark for row in rows if row.mark]
                if graded:
                    notes.append(f"Средний балл по закрытым дисциплинам: {sum(graded) / len(graded):.2f}.")
            else:
                notes.append("Закрытых семестров пока нет: студент учится на первом курсе первого семестра.")
        elif code == "CERT_INTERN":
            paragraphs.append(f"Справка подтверждает, что <b>{student.full_name}</b> обучается на {group.course} курсе и "
                              f"направляется для прохождения стажировки (практики) в организацию "
                              f"{fields.get('organization', '')} в период с {fields.get('period_from', '')} по {fields.get('period_to', '')}.")
        elif code == "CERT_MIL":
            paragraphs.append(f"Справка выдана <b>{student.full_name}</b> для предъявления в {fields.get('office', 'военный комиссариат')} "
                              f"(цель: {fields.get('purpose', '').lower()}). Студент обучается по {FORMS_DATIVE.get(student.study_form, 'очной')} форме, "
                              f"нормативный срок окончания обучения — по учебному плану направления.")
        elif code == "RETAKE":
            paragraphs.append(f"<b>{student.full_name}</b> направляется на пересдачу по дисциплине "
                              f"«{fields.get('discipline', '')}».")
        else:
            paragraphs.append(f"По заявке «{request.type.title}» студента <b>{student.full_name}</b> принято решение.")
        if request.result_note:
            paragraphs.append(f"Комментарий деканата: {request.result_note}")
        content = DocumentContent(
            title=document.title, number=request.number, issued_on=issued_on, paragraphs=paragraphs, facts=facts,
            verify_url=url, signature=self.link_sig(public_id, now), table=table, table_title=table_title, notes=notes,
        )
        pdf = render(content)
        digest = hashlib.sha256(pdf).hexdigest()
        document.pdf = pdf
        document.sha256 = digest
        document.signature = self._mac(f"{public_id}|{now.isoformat()}|{digest}")
        db.add(document)
        await db.flush()
        return document

    async def download(self, user: User, request_id: uuid.UUID, base_url: str) -> Document:
        document = await self.ensure(user, request_id, base_url)
        async with self.database.session() as db:
            db.add(AuditLog(actor_id=user.id, action="document.download", object_type="document", object_id=str(document.id)))
            await db.commit()
        return document

    async def revoke(self, user: User, request_id: uuid.UUID, reason: str) -> Document:
        if user.role not in ("staff", "admin"):
            raise ApiError(404, "not_found", "Заявка не найдена.")
        async with self.database.session() as db:
            request = await self._request(db, user, request_id)
            document = await db.scalar(select(Document).where(Document.request_id == request.id))
            if document is None:
                raise ApiError(404, "not_found", "Документ ещё не выпущен.")
            if document.revoked_at is None:
                document.revoked_at = self.clock()
                document.revoke_reason = reason.strip()[:500] or "Отозван деканатом"
                db.add(AuditLog(actor_id=user.id, action="document.revoke", object_type="document", object_id=str(document.id)))
                await db.commit()
            return document

    # ---- public check ------------------------------------------------------

    async def verify(self, token: str) -> dict | None:
        public_id, _, sig = token.partition(".")
        if len(public_id) != 16 or not sig or len(token) > 64:
            return None
        async with self.database.session() as db:
            document = await db.scalar(select(Document).where(Document.public_id == public_id))
        if document is None:
            return None
        if not hmac.compare_digest(self.link_sig(document.public_id, document.issued_at), sig):
            return None
        intact = hmac.compare_digest(
            document.signature, self._mac(f"{document.public_id}|{document.issued_at.isoformat()}|{document.sha256}")
        )
        if not intact:
            return None
        return {
            "valid": True,
            "status": "revoked" if document.revoked_at else "active",
            "status_label": "Отозван" if document.revoked_at else "Действует",
            "title": document.title,
            "number": document.number,
            "issued_at": document.issued_at.isoformat(),
            "holder": document.holder_initials,
            "sha256": document.sha256,
            "revoked_at": document.revoked_at.isoformat() if document.revoked_at else None,
        }

    def meta(self, document: Document, base_url: str) -> dict:
        return {
            "id": str(document.id),
            "title": document.title,
            "number": document.number,
            "issued_at": document.issued_at.isoformat(),
            "verify_url": self.verify_url(document, base_url),
            "sha256": document.sha256,
            "size": len(document.pdf),
            "revoked": document.revoked_at is not None,
            "revoke_reason": document.revoke_reason,
        }
