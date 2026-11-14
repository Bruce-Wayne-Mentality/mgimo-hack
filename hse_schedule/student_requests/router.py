"""HTTP API for requests (section 9.2): student endpoints and the staff queue."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import Depends, FastAPI, Header, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from ..accounts.router import ApiError
from ..accounts.service import CurrentSession
from .catalog import display_payload
from .models import StudentRequest
from .service import (
    CLOSED_STATUSES,
    STATUS_LABELS,
    STUDENT_COMMENT_STATUSES,
    TRANSITIONS,
    RequestError,
    RequestService,
)

# Tracker steps shown to the student (K2): Принята → В работе → Готова.
TRACK = ("submitted", "in_review", "ready")


class CreateBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    type_code: StrictStr = Field(min_length=1, max_length=32)
    payload: dict = Field(default_factory=dict)


class CommentBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: StrictStr = Field(min_length=1, max_length=2000)
    internal: StrictBool = False


class TransitionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    to: Literal["in_review", "needs_info", "ready", "rejected"]
    note: StrictStr | None = Field(default=None, max_length=2000)


def type_payload(request_type) -> dict:
    return {
        "code": request_type.code,
        "title": request_type.title,
        "description": request_type.description,
        "result": request_type.result,
        "sla_days": request_type.sla_days,
        "auto_issue": request_type.auto_issue,
        "fields": request_type.fields,
    }


def summary_payload(request: StudentRequest) -> dict:
    return {
        "id": str(request.id),
        "number": request.number,
        "type": {"code": request.type.code, "title": request.type.title},
        "status": request.status,
        "status_label": STATUS_LABELS[request.status],
        "created_at": request.created_at.isoformat(),
        "updated_at": request.updated_at.isoformat(),
        "due_at": request.due_at.isoformat(),
        "closed_at": request.closed_at.isoformat() if request.closed_at else None,
    }


def detail_payload(request: StudentRequest, *, staff: bool, viewer_id: uuid.UUID) -> dict:
    events = [
        {
            "from": event.from_status,
            "to": event.to_status,
            "label": STATUS_LABELS[event.to_status],
            "at": event.at.isoformat(),
            "note": event.note,
            "by_system": event.actor_id is None,
        }
        for event in request.events
    ]
    reached = {event.to_status: event.at for event in request.events}
    track = [
        {"status": status, "label": STATUS_LABELS[status], "at": reached[status].isoformat() if status in reached else None}
        for status in TRACK
    ]
    comments = [
        {
            "id": str(comment.id),
            "body": comment.body,
            "at": comment.created_at.isoformat(),
            "internal": comment.internal,
            "mine": comment.author_id == viewer_id,
            "author": (
                "Вы" if comment.author_id == viewer_id
                else "Деканат" if comment.author is None or comment.author.role != "student"
                else comment.author.display_name if staff else "Вы"
            ),
            "from_staff": comment.author is not None and comment.author.role != "student",
        }
        for comment in request.comments
        if staff or not comment.internal
    ]
    data = {
        **summary_payload(request),
        "type": type_payload(request.type),
        "fields": display_payload(request.type.fields, request.payload),
        "events": events,
        "track": track,
        "comments": comments,
        "result_note": request.result_note,
        "can_cancel": not staff and (request.status, "cancelled") in TRANSITIONS,
        "can_reply": not staff and request.status in STUDENT_COMMENT_STATUSES,
    }
    if staff:
        student = request.student
        data["student"] = {
            "full_name": student.full_name,
            "group": student.group.code,
            "course": student.group.course,
            "faculty": student.group.faculty.title,
            "record_book_no": student.record_book_no,
            "status": student.status,
        }
        data["actions"] = [
            {"to": to, "label": STATUS_LABELS[to], "note_required": rule["note"]}
            for (origin, to), rule in TRANSITIONS.items()
            if origin == request.status and "staff" in rule["by"]
        ]
        data["closed"] = request.status in CLOSED_STATUSES
    return data


def register_request_routes(app: FastAPI, service: RequestService) -> None:
    require_session = app.state.require_session

    def fail(error: RequestError):
        raise ApiError(error.status, error.code, error.message, fields=error.fields)

    @app.get("/api/request-types", tags=["requests"])
    async def request_types(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": [type_payload(item) for item in await service.list_types()]}

    @app.get("/api/requests", tags=["requests"])
    async def my_requests(current: CurrentSession = Depends(require_session)) -> dict:
        try:
            items = await service.list_own(current.user)
        except RequestError as error:
            fail(error)
        return {"items": [summary_payload(item) for item in items]}

    @app.post("/api/requests", tags=["requests"])
    async def create_request(
        body: CreateBody,
        response: Response,
        current: CurrentSession = Depends(require_session),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict:
        try:
            request, created = await service.create(current.user, body.type_code, body.payload, idempotency_key)
        except RequestError as error:
            fail(error)
        response.status_code = 201 if created else 200
        return detail_payload(request, staff=False, viewer_id=current.user.id)

    def parse_id(value: str) -> uuid.UUID:
        try:
            return uuid.UUID(value)
        except ValueError:
            raise ApiError(404, "not_found", "Заявка не найдена.") from None

    @app.get("/api/requests/{request_id}", tags=["requests"])
    async def request_detail(request_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        if current.user.role != "student":
            raise ApiError(404, "not_found", "Заявка не найдена.")
        try:
            request = await service.get(current.user, parse_id(request_id))
        except RequestError as error:
            fail(error)
        return detail_payload(request, staff=False, viewer_id=current.user.id)

    @app.post("/api/requests/{request_id}/cancel", tags=["requests"])
    async def cancel_request(request_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        try:
            request = await service.cancel(current.user, parse_id(request_id))
        except RequestError as error:
            fail(error)
        return detail_payload(request, staff=False, viewer_id=current.user.id)

    @app.post("/api/requests/{request_id}/comments", tags=["requests"])
    async def comment_request(request_id: str, body: CommentBody, current: CurrentSession = Depends(require_session)) -> dict:
        try:
            request = await service.comment(current.user, parse_id(request_id), body.body, internal=body.internal)
        except RequestError as error:
            fail(error)
        staff = current.user.role != "student"
        return detail_payload(request, staff=staff, viewer_id=current.user.id)

    # ---- staff (S1) -------------------------------------------------------

    @app.get("/api/staff/requests", tags=["staff"])
    async def staff_queue(
        status: str | None = Query(default=None, max_length=16),
        type: str | None = Query(default=None, max_length=32),
        overdue: bool = False,
        current: CurrentSession = Depends(require_session),
    ) -> dict:
        try:
            items = await service.staff_queue(current.user, status=status, type_code=type, overdue=overdue)
        except RequestError as error:
            fail(error)
        now = service.clock()
        return {
            "items": [
                {
                    **summary_payload(item),
                    "student": {"full_name": item.student.full_name, "group": item.student.group.code},
                    "overdue": item.status not in CLOSED_STATUSES and item.due_at < now,
                }
                for item in items
            ]
        }

    @app.get("/api/staff/requests/{request_id}", tags=["staff"])
    async def staff_detail(request_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        if current.user.role not in ("staff", "admin"):
            raise ApiError(404, "not_found", "Заявка не найдена.")
        try:
            request = await service.get(current.user, parse_id(request_id))
        except RequestError as error:
            fail(error)
        return detail_payload(request, staff=True, viewer_id=current.user.id)

    @app.post("/api/staff/requests/{request_id}/transition", tags=["staff"])
    async def staff_transition(request_id: str, body: TransitionBody, current: CurrentSession = Depends(require_session)) -> dict:
        try:
            request = await service.staff_transition(current.user, parse_id(request_id), body.to, body.note)
        except RequestError as error:
            fail(error)
        return detail_payload(request, staff=True, viewer_id=current.user.id)

    @app.exception_handler(RequestError)
    async def request_error(_request, error: RequestError):
        body = {"code": error.code, "message": error.message}
        if error.fields:
            body["fields"] = error.fields
        return JSONResponse(status_code=error.status, content={"error": body})
