"""K2 documents: authorised download, staff revoke and the public check."""

from __future__ import annotations

import uuid
from urllib.parse import quote

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictStr

from ..accounts.router import ApiError
from ..accounts.service import CurrentSession
from ..ratelimit import RateLimiter
from .service import DocumentService


class RevokeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    reason: StrictStr = Field(min_length=3, max_length=500)


def _id(value: str) -> uuid.UUID:
    try:
        return uuid.UUID(value)
    except ValueError:
        raise ApiError(404, "not_found", "Заявка не найдена.") from None


def register_document_routes(app: FastAPI, service: DocumentService) -> None:
    require_session = app.state.require_session
    public_limit = RateLimiter(limit=30, window=60)

    def base(request: Request) -> str:
        return str(request.base_url)

    @app.get("/api/requests/{request_id}/document", tags=["documents"])
    async def document_meta(request_id: str, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        document = await service.ensure(current.user, _id(request_id), base(request))
        return service.meta(document, base(request))

    @app.get("/api/requests/{request_id}/document.pdf", tags=["documents"])
    async def document_pdf(request_id: str, request: Request, current: CurrentSession = Depends(require_session)) -> Response:
        document = await service.download(current.user, _id(request_id), base(request))
        filename = f"{document.number}.pdf"
        return Response(
            document.pdf, media_type="application/pdf",
            headers={
                "Content-Disposition": f"inline; filename=\"document.pdf\"; filename*=UTF-8''{quote(filename)}",
                "Cache-Control": "private, no-store",
            },
        )

    @app.post("/api/staff/requests/{request_id}/document/revoke", tags=["documents"])
    async def revoke(request_id: str, body: RevokeBody, request: Request, current: CurrentSession = Depends(require_session)) -> dict:
        document = await service.revoke(current.user, _id(request_id), body.reason)
        return service.meta(document, base(request))

    @app.get("/api/verify/{token}", tags=["public"])
    async def verify(token: str, request: Request) -> dict:
        public_limit.check(request, "verify")
        result = await service.verify(token)
        if result is None:
            raise ApiError(404, "not_found", "Документ не найден.")
        return result
