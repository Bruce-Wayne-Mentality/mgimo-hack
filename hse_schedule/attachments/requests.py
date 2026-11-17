"""Attachments in request chats.

Upload first, send later: POST the file (raw body, the name in X-File-Name), get
its id, then send the comment with attachment_ids. A file that was never sent is
visible only to its uploader and is removed after a day.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import timedelta
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, Request
from fastapi.responses import Response
from sqlalchemy import select

from ..accounts.policy import can_open_request_attachment
from ..accounts.router import ApiError
from ..accounts.service import CurrentSession
from ..db import utcnow
from ..ratelimit import RateLimiter
from ..student_requests import policy as request_policy
from ..student_requests.service import STUDENT_COMMENT_STATUSES
from . import storage
from .files import AttachmentError, limits, prepare
from .models import RequestAttachment

STAGED_TTL = timedelta(hours=24)


def attachment_payload(row, url: str) -> dict:
    return {"id": str(row.id), "name": row.name, "kind": row.kind, "size": row.size, "url": url}


def request_attachment_url(request_id, attachment_id) -> str:
    return f"/api/requests/{request_id}/attachments/{attachment_id}"


async def read_upload(request: Request) -> tuple[bytes, str | None]:
    """The raw body, cut off one byte past the limit (no unbounded reads); the name from X-File-Name."""
    cap = limits().max_bytes
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            raise AttachmentError("too_large", f"Файл больше {limits().max_mb} МБ. Сожмите его или разделите на части.", status=413)
        chunks.append(chunk)
    name = request.headers.get("x-file-name")
    return b"".join(chunks), unquote(name) if name else None


def download(data: bytes, name: str, mime: str) -> Response:
    ascii_name = name.encode("ascii", "replace").decode().replace("?", "_").replace('"', "_")
    return Response(content=data, media_type=mime, headers={
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}",
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
        "Content-Security-Policy": "default-src 'none'; sandbox",
    })


def not_found() -> ApiError:
    return ApiError(404, "not_found", "Файл не найден.")


def register_request_attachment_routes(app: FastAPI, database, service) -> None:
    require_session = app.state.require_session
    uploads = RateLimiter(limit=20, window=60)
    downloads = RateLimiter(limit=120, window=60)

    async def visible_request(db, user, request_id: uuid.UUID):
        request = await service._load(db, request_id)
        if request is None or not request_policy.can_view_request(user, request):
            raise not_found()
        return request

    @app.post("/api/requests/{request_id}/attachments", status_code=201, tags=["requests"])
    async def upload(request_id: uuid.UUID, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        uploads.check(request, "attachment-upload", str(current.user.id))
        user = current.user
        try:
            raw, name = await read_upload(request)
            prepared = prepare(raw, name)
        except AttachmentError as error:
            raise ApiError(error.status, error.code, error.message) from None
        now = utcnow()
        async with database.session() as db:
            target = await visible_request(db, user, request_id)
            if user.role == "student" and target.status not in STUDENT_COMMENT_STATUSES:
                raise ApiError(409, "invalid_state", "По закрытой заявке прикреплять файлы нельзя.")
            stale = (await db.scalars(select(RequestAttachment).where(
                RequestAttachment.comment_id.is_(None), RequestAttachment.created_at < now - STAGED_TTL))).all()
            for row in stale:  # files uploaded and never sent: gone after a day
                storage.delete(row.storage_key)
                await db.delete(row)
            pending = (await db.scalars(select(RequestAttachment.id).where(
                RequestAttachment.request_id == request_id, RequestAttachment.uploader_id == user.id,
                RequestAttachment.comment_id.is_(None)))).all()
            if len(pending) >= limits().max_files * 2:
                raise ApiError(429, "too_many_files", "Слишком много неотправленных файлов. Отправьте сообщение или уберите лишние.")
            key = storage.write(prepared.data)
            row = RequestAttachment(request_id=request_id, uploader_id=user.id, name=prepared.name, kind=prepared.kind,
                                    mime=prepared.mime, size=len(prepared.data), storage_key=key,
                                    sha256=hashlib.sha256(prepared.data).hexdigest(), created_at=now)
            db.add(row)
            await db.commit()
            return attachment_payload(row, request_attachment_url(request_id, row.id))

    @app.delete("/api/requests/{request_id}/attachments/{attachment_id}", status_code=204, tags=["requests"])
    async def remove(request_id: uuid.UUID, attachment_id: uuid.UUID, request: Request,
                     current: CurrentSession = Depends(require_session)) -> Response:
        uploads.check(request, "attachment-upload", str(current.user.id))
        async with database.session() as db:
            row = await db.get(RequestAttachment, attachment_id)
            if row is None or row.request_id != request_id or row.comment_id is not None or row.uploader_id != current.user.id:
                raise not_found()  # sent files stay with the message
            storage.delete(row.storage_key)
            await db.delete(row)
            await db.commit()
        return Response(status_code=204)

    @app.get("/api/requests/{request_id}/attachments/{attachment_id}", tags=["requests"])
    async def get(request_id: uuid.UUID, attachment_id: uuid.UUID, request: Request,
                  current: CurrentSession = Depends(require_session)) -> Response:
        downloads.check(request, "attachment-download", str(current.user.id))
        user = current.user
        async with database.session() as db:
            row = await db.get(RequestAttachment, attachment_id)
            if row is None or row.request_id != request_id:
                raise not_found()
            target = await service._load(db, request_id)
            internal = False
            if row.comment_id is not None:
                from ..student_requests.models import RequestComment

                comment = await db.get(RequestComment, row.comment_id)
                internal = bool(comment and comment.internal)
            allowed = target is not None and can_open_request_attachment(
                user, sees_request=request_policy.can_view_request(user, target), internal=internal,
                uploader_id=row.uploader_id, sent=row.comment_id is not None)
            if not allowed:
                raise not_found()  # someone else's file looks exactly like a missing one
            name, mime, key = row.name, row.mime, row.storage_key
        data = storage.read(key)
        if data is None:
            raise not_found()
        return download(data, name, mime)
