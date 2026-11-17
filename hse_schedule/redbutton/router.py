"""Red button HTTP API (spec, section 7). The owner always comes from the session;
someone else's complaint answers 404, never 403. Request bodies are not logged."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import Depends, FastAPI, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from ..accounts.router import ApiError
from ..accounts.service import CurrentSession
from ..ratelimit import RateLimiter
from .service import RedButtonService


class SubmitBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: uuid.UUID | None = None
    type: Literal["unfair", "problem", "suggestion", "thanks"] = "unfair"
    category: Literal["grades", "schedule", "teacher_conduct", "dean_office", "documents", "scholarship_payment",
                      "dormitory", "infrastructure", "other"] | None = None
    link_type: Literal["discipline", "lesson", "request", "room"] | None = None
    link_id: StrictStr | None = Field(default=None, max_length=64)
    link_label: StrictStr | None = Field(default=None, max_length=120)
    text: StrictStr = Field(min_length=30, max_length=3000)
    desired_outcome: Literal["review", "explain", "fix", "record"] | None = None
    privacy: Literal["named", "confidential", "anonymous"] = "confidential"


class SessionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: uuid.UUID


class MessageBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: StrictStr = Field(min_length=1, max_length=3000)


class FeedbackBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    resolved: StrictBool
    comment: StrictStr | None = Field(default=None, max_length=2000)


class ActionBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["accept", "return", "take", "need_info", "answer", "message"]
    text: StrictStr | None = Field(default=None, max_length=3000)


class AssignBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assignee_id: uuid.UUID


def _id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ApiError(404, "not_found", "Обращение не найдено.") from None


def register_redbutton_routes(app: FastAPI, service: RedButtonService) -> None:
    require_session = app.state.require_session
    submit_limit = RateLimiter(limit=20, window=600)

    def student(current: CurrentSession):
        if current.user.role != "student" or current.user.student is None:
            raise ApiError(403, "forbidden", "Раздел для студентов.")
        service.ensure_worker()
        return current.user

    @app.post("/api/complaints", tags=["complaints"])
    async def submit(body: SubmitBody, request: Request, current: CurrentSession = Depends(require_session)):
        user = student(current)
        # Attempts are limited by a hashed account key kept in memory only.
        submit_limit.check(request, "complaint-submit", str(user.id))
        status, payload = await service.submit(user, body.model_dump(), body.text)
        return JSONResponse(payload, status_code=status)

    @app.post("/api/complaints/manual-review", status_code=201, tags=["complaints"])
    async def manual_review(body: SessionBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.manual_review(student(current), body.session_id)

    @app.get("/api/complaints", tags=["complaints"])
    async def mine(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.list_own(student(current))}

    @app.get("/api/complaints/{complaint_id}", tags=["complaints"])
    async def one(complaint_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.student_view(_id(complaint_id), student(current))

    @app.post("/api/complaints/{complaint_id}/messages", tags=["complaints"])
    async def message(complaint_id: str, body: MessageBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.message(student(current), _id(complaint_id), body.text)

    @app.post("/api/complaints/{complaint_id}/feedback", tags=["complaints"])
    async def feedback(complaint_id: str, body: FeedbackBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.feedback(student(current), _id(complaint_id), body.resolved, body.comment)

    @app.delete("/api/complaints/{complaint_id}", status_code=204, tags=["complaints"])
    async def withdraw(complaint_id: str, current: CurrentSession = Depends(require_session)) -> None:
        await service.withdraw(student(current), _id(complaint_id))

    # ---- staff: executor and curator --------------------------------------------------

    def staff(current: CurrentSession):
        if service.role(current.user) is None:
            raise ApiError(403, "forbidden", "Раздел для сотрудников.")
        service.ensure_worker()
        return current.user

    @app.get("/api/staff/complaints", tags=["staff"])
    async def queue(status: str | None = Query(default=None, max_length=16), category: str | None = Query(default=None, max_length=32),
                    current: CurrentSession = Depends(require_session)) -> dict:
        return await service.queue(staff(current), status=status, category=category)

    @app.get("/api/staff/complaints/{complaint_id}", tags=["staff"])
    async def staff_one(complaint_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.staff_view(staff(current), _id(complaint_id))

    @app.post("/api/staff/complaints/{complaint_id}/status", tags=["staff"])
    async def act(complaint_id: str, body: ActionBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.act(staff(current), _id(complaint_id), body.action, body.text)

    @app.post("/api/staff/complaints/{complaint_id}/assign", tags=["staff"])
    async def assign(complaint_id: str, body: AssignBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.assign(staff(current), _id(complaint_id), body.assignee_id)

    @app.get("/api/staff/moderation", tags=["staff"])
    async def moderation(current: CurrentSession = Depends(require_session)) -> dict:
        user = staff(current)
        if service.role(user) != "curator":
            raise ApiError(403, "forbidden", "Ручная модерация — у куратора кнопки.")
        return await service.queue(user, status="MODERATION")
