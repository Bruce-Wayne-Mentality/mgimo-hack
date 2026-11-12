"""HTTP integration for an authenticated student's personal timetable."""

from __future__ import annotations

import hmac
from collections.abc import Mapping
from contextlib import asynccontextmanager
from datetime import date

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import ConfigurationError, InvalidPayload, SourceUnavailable, UnknownStudent
from .service import ScheduleService
from .validation import validate_date_range


def create_app(
    service: ScheduleService,
    tokens: Mapping[str, str],
    *,
    demo: bool = False,
    notification_store=None,
    push_sender=None,
    telegram_bot=None,
    run_workers: bool = False,
    refresh_interval: float = 60,
) -> FastAPI:
    """Create the API with server-issued bearer tokens mapped to account emails.

    A host application can replace the authentication dependency with its own
    verified session/JWT identity. Never take the account email from query data.
    """
    account_tokens = tuple(tokens.items())
    if any(
        not isinstance(token, str)
        or not token.strip()
        or not isinstance(email, str)
        or not email.strip()
        for token, email in account_tokens
    ):
        raise ConfigurationError("Токены доступа должны соответствовать email аккаунтов.")

    @asynccontextmanager
    async def lifespan(app):
        runtime = None
        if notification_store is not None and run_workers:
            from .notification_runtime import NotificationDispatcher, NotificationRuntime
            from .notifications import NotificationEngine

            runtime = NotificationRuntime(
                NotificationEngine(service, notification_store),
                NotificationDispatcher(notification_store, service.directory, push_sender=push_sender, telegram_bot=telegram_bot),
                telegram_bot=telegram_bot,
                refresh_interval=refresh_interval,
            )
            runtime.start()
        try:
            yield
        finally:
            if runtime is not None:
                import asyncio

                await asyncio.to_thread(runtime.stop)

    app = FastAPI(
        title="Личное расписание",
        description="Расписание студента определяется подтверждённой учётной записью.",
        version="0.1.0",
        lifespan=lifespan,
    )
    bearer = HTTPBearer(auto_error=False)

    def authenticated_email(
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    ) -> str:
        if credentials is not None:
            supplied = credentials.credentials.encode("utf-8")
            for token, email in account_tokens:
                if hmac.compare_digest(supplied, token.encode("utf-8")):
                    return email
        raise HTTPException(
            status_code=401,
            detail="Требуется действительный токен аккаунта.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # An existing site's trusted identity resolver can override this dependency.
    app.state.account_dependency = authenticated_email

    @app.middleware("http")
    async def private_responses(request: Request, call_next):
        response = await call_next(request)
        if request.url.path.startswith("/api/"):
            response.headers["Cache-Control"] = "private, no-store"
        return response

    @app.exception_handler(UnknownStudent)
    async def unknown_student(_request: Request, _error: UnknownStudent):
        return JSONResponse(
            status_code=404,
            content={"detail": "Студент с таким аккаунтом не зарегистрирован."},
        )

    @app.exception_handler(SourceUnavailable)
    async def source_unavailable(_request: Request, _error: SourceUnavailable):
        return JSONResponse(
            status_code=502,
            content={"detail": "Источник расписания временно недоступен."},
        )

    @app.exception_handler(InvalidPayload)
    async def invalid_source(_request: Request, _error: InvalidPayload):
        return JSONResponse(
            status_code=502,
            content={"detail": "Источник вернул некорректное расписание."},
        )

    @app.exception_handler(ConfigurationError)
    async def invalid_configuration(_request: Request, _error: ConfigurationError):
        return JSONResponse(
            status_code=503,
            content={"detail": "Настройки личного расписания требуют проверки."},
        )

    @app.get("/health")
    def health() -> dict:
        return {"status": "ok", "demo": demo}

    @app.get("/api/me")
    def current_student(email: str = Depends(authenticated_email)) -> dict:
        student = service.directory.get(email)
        return {"email": student.email, "name": student.name}

    @app.get("/api/me/schedule")
    def personal_schedule(
        start: date,
        finish: date,
        email: str = Depends(authenticated_email),
    ) -> dict:
        try:
            validate_date_range(start, finish)
        except ValueError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        student = service.directory.get(email)
        lessons = service.get_schedule(email, start, finish)
        return {
            "student": {"email": student.email, "name": student.name},
            "start": start.isoformat(),
            "finish": finish.isoformat(),
            "timezone": getattr(service, "timezone", "Europe/Moscow"),
            "lessons": [lesson.to_dict() for lesson in lessons],
            "demo": demo,
        }

    if notification_store is not None:
        from .notification_api import register_notification_routes

        register_notification_routes(
            app, service, notification_store, authenticated_email,
            push_sender=push_sender, telegram_bot=telegram_bot, demo=demo,
        )

    return app
