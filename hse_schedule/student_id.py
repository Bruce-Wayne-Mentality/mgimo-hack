"""K3: digital student card with a dynamic QR code.

The QR holds a link to /id/<token>; token = payload.sig where payload is
base64url JSON {sid, iat, exp, nonce} and sig = HMAC-SHA256 (truncated).
Lifetime 60 s, so a screenshot stops working quickly. The public check shows
only name, group, status and the remaining lifetime.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
import uuid
from collections.abc import Callable

import segno
from fastapi import Depends, FastAPI, Request
from sqlalchemy import select

from .accounts.models import Student
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Database
from .ratelimit import RateLimiter

LIFETIME = 60
STATUS_LABELS = {"active": "Обучается", "academic_leave": "Академический отпуск", "expelled": "Отчислен", "graduated": "Выпускник"}


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode().rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


class StudentIdService:
    def __init__(self, database: Database, secret: bytes, *, clock: Callable[[], float] = time.time,
                 base_url: str | None = None) -> None:
        self.database = database
        self.key = hmac.new(secret, b"student-id-v1", hashlib.sha256).digest()
        self.clock = clock
        self.base_url = base_url.rstrip("/") if base_url else None

    def issue(self, student_id: uuid.UUID) -> tuple[str, int]:
        now = int(self.clock())
        payload = _b64(json.dumps({"sid": student_id.hex, "iat": now, "exp": now + LIFETIME,
                                   "nonce": secrets.token_hex(4)}, separators=(",", ":")).encode())
        sig = _b64(hmac.new(self.key, payload.encode(), hashlib.sha256).digest()[:18])
        return f"{payload}.{sig}", now + LIFETIME

    def read(self, token: str) -> dict | None:
        payload, _, sig = token.partition(".")
        if not payload or not sig or len(token) > 200:
            return None
        expected = _b64(hmac.new(self.key, payload.encode(), hashlib.sha256).digest()[:18])
        if not hmac.compare_digest(expected, sig):
            return None
        try:
            data = json.loads(_unb64(payload))
            return {"sid": uuid.UUID(hex=data["sid"]), "iat": int(data["iat"]), "exp": int(data["exp"])}
        except (ValueError, KeyError, TypeError):
            return None


def register_student_id_routes(app: FastAPI, service: StudentIdService) -> None:
    require_session = app.state.require_session
    check_limit = RateLimiter(limit=60, window=60)

    @app.get("/api/student-id", tags=["student-id"])
    async def card(request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        student = current.user.student
        if current.user.role != "student" or student is None:
            raise ApiError(403, "forbidden", "Студенческий билет есть только у студентов.")
        token, expires = service.issue(student.id)
        url = f"{service.base_url or str(request.base_url).rstrip('/')}/id/{token}"
        qr = segno.make(url, error="m")
        svg = qr.svg_inline(scale=1, border=2, dark="#000000", light="#ffffff", omitsize=True)
        group = student.group
        return {
            "full_name": student.full_name,
            "record_book_no": student.record_book_no,
            "card_no": f"СБ-{student.record_book_no.removeprefix('DEMO-')}",
            "group": group.code,
            "course": group.course,
            "faculty": group.faculty.title,
            "program": f"{group.program_code} {group.program_title}",
            "status": student.status,
            "status_label": STATUS_LABELS.get(student.status, student.status),
            "valid_until": "31.08.2030",
            "token": token,
            "url": url,
            "qr_svg": svg,
            "expires_at": expires,
            "server_time": int(service.clock()),
            "lifetime": LIFETIME,
        }

    @app.get("/api/id-check/{token}", tags=["public"])
    async def check(token: str, request: Request) -> dict:
        check_limit.check(request, "id-check")
        data = service.read(token)
        if data is None:
            raise ApiError(404, "not_found", "Код не распознан.")
        now = int(service.clock())
        async with service.database.session() as db:
            student = await db.scalar(select(Student).where(Student.id == data["sid"]))
        if student is None:
            raise ApiError(404, "not_found", "Код не распознан.")
        left = data["exp"] - now
        return {
            "valid": left > 0 and student.status == "active",
            "expired": left <= 0,
            "seconds_left": max(0, left),
            "full_name": student.full_name if left > 0 else None,
            "group": student.group.code if left > 0 else None,
            "faculty": student.group.faculty.title if left > 0 else None,
            "status": student.status,
            "status_label": STATUS_LABELS.get(student.status, student.status),
            "checked_at": now,
        }
