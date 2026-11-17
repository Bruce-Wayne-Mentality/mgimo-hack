"""HTTP API for study records, the traffic light, nudges and the staff gradebook."""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from ..accounts.router import ApiError
from ..accounts.service import CurrentSession
from .service import AcademicService


class WhatIfBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    scores: dict[str, float] = Field(default_factory=dict, max_length=20)


class NudgeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    state: Literal["seen", "done", "dismissed"]
    mute: StrictBool = False


class GradeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    student_id: StrictStr
    checkpoint_id: StrictStr
    score: float | None = Field(default=None, ge=0, le=1000)
    reason: StrictStr | None = Field(default=None, max_length=500)


def parse_id(value: str, message: str = "Не найдено.") -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ApiError(404, "not_found", message) from None


def register_academic_routes(app: FastAPI, service: AcademicService) -> None:
    require_session = app.state.require_session

    @app.get("/api/study", tags=["study"])
    async def study_overview(current: CurrentSession = Depends(require_session)) -> dict:
        return await service.overview(current.user)

    @app.get("/api/study/disciplines/{discipline_id}", tags=["study"])
    async def study_discipline(discipline_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.discipline(current.user, parse_id(discipline_id, "Дисциплина не найдена."))

    @app.post("/api/study/disciplines/{discipline_id}/what-if", tags=["study"])
    async def study_what_if(discipline_id: str, body: WhatIfBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.what_if(current.user, parse_id(discipline_id, "Дисциплина не найдена."), body.scores)

    @app.get("/api/nudges", tags=["study"])
    async def nudges(current: CurrentSession = Depends(require_session)) -> dict:
        if current.user.role != "student":
            return {"items": []}
        return {"items": await service.nudges(current.user)}

    @app.post("/api/nudges/{nudge_id}", status_code=204, tags=["study"])
    async def update_nudge(nudge_id: str, body: NudgeBody, current: CurrentSession = Depends(require_session)) -> None:
        await service.update_nudge(current.user, parse_id(nudge_id, "Подсказка не найдена."), body.state, body.mute)

    @app.get("/api/staff/gradebook", tags=["staff"])
    async def gradebook_groups(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.staff_groups(current.user)}

    @app.get("/api/staff/gradebook/{discipline_id}", tags=["staff"])
    async def gradebook(discipline_id: str, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.gradebook(current.user, parse_id(discipline_id, "Дисциплина не найдена."))

    @app.put("/api/staff/gradebook/{discipline_id}/grades", tags=["staff"])
    async def set_grade(discipline_id: str, body: GradeBody, current: CurrentSession = Depends(require_session)) -> dict:
        return await service.set_grade(
            current.user, parse_id(discipline_id, "Дисциплина не найдена."),
            parse_id(body.student_id, "Студент не найден."), parse_id(body.checkpoint_id, "Контрольная точка не найдена."),
            body.score, body.reason,
        )
