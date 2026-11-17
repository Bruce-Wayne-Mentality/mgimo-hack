"""HTTP integration for an authenticated student's personal timetable."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Security
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .errors import ConfigurationError, InvalidPayload, SourceUnavailable, UnknownStudent
from .service import ScheduleService
from .validation import validate_date_range


PRIVATE_LOG_PREFIXES = ("/api/complaints", "/api/staff/complaints", "/api/staff/moderation")


class _NoAddressForComplaints(logging.Filter):
    """Spec «Красная кнопка», §6: no IP address in logs for the complaints routes."""

    def filter(self, record: logging.LogRecord) -> bool:
        args = record.args
        if isinstance(args, tuple) and len(args) >= 3 and isinstance(args[2], str) and args[2].startswith(PRIVATE_LOG_PREFIXES):
            record.args = ("-", *args[1:2], args[2].split("?", 1)[0], *args[3:])
        return True


def install_access_log_filter() -> None:
    logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, _NoAddressForComplaints) for f in logger.filters):
        logger.addFilter(_NoAddressForComplaints())


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
    auth=None,
    auth_settings=None,
    demo_accounts: Sequence[Mapping[str, str]] = (),
    web_dist: Path | None = None,
    request_service=None,
    modules: Sequence = (),
) -> FastAPI:
    """Create the API.

    Identity comes from a server-side session cookie when ``auth`` (an
    AuthService) is given, and/or from server-issued bearer tokens mapped to
    account emails. A host application can replace the authentication
    dependency with its own verified identity. Never take the account email
    from query data.
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
        install_access_log_filter()
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

    from .web import add_security_headers

    add_security_headers(app)
    require_session = None
    if auth is not None:
        from .accounts.router import register_auth_routes

        require_session = register_auth_routes(app, auth, auth_settings, demo_accounts=demo_accounts)
    else:
        async def no_session(_request: Request):
            return None

        app.state.optional_session = no_session

    async def authenticated_email(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Security(bearer),
    ) -> str:
        if credentials is not None:
            supplied = credentials.credentials.encode("utf-8")
            for token, email in account_tokens:
                if hmac.compare_digest(supplied, token.encode("utf-8")):
                    return email
        if require_session is not None and credentials is None:
            from .accounts.policy import schedule_email

            current = await require_session(request)
            email = schedule_email(current.user)
            if email is None:
                raise HTTPException(status_code=404, detail="Личное расписание доступно только студентам.")
            return email
        raise HTTPException(
            status_code=401,
            detail="Требуется действительный токен аккаунта.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # An existing site's trusted identity resolver can override this dependency.
    app.state.account_dependency = authenticated_email

    from .ratelimit import RateLimiter

    # A coarse per-address ceiling for the whole API on top of the per-feature
    # limits (login throttle, public checks): a stuck script or a flood gets 429.
    read_limit = RateLimiter(limit=600, window=60)
    write_limit = RateLimiter(limit=120, window=60)

    @app.middleware("http")
    async def api_rate_limit(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            client = request.client.host if request.client else "unknown"
            limiter = read_limit if request.method in ("GET", "HEAD", "OPTIONS") else write_limit
            wait = limiter.hit(f"api|{client}")
            if wait is not None:
                return JSONResponse(
                    {"error": {"code": "rate_limited", "message": "Слишком много запросов. Подождите немного."}},
                    status_code=429, headers={"Retry-After": str(int(wait) + 1)},
                )
        return await call_next(request)

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
    async def health() -> JSONResponse:
        database = getattr(app.state, "database", None)
        status = {"status": "ok", "demo": demo}
        if database is not None:
            from sqlalchemy import text

            try:
                async with database.session() as db:
                    await db.execute(text("SELECT 1"))
                status["database"] = "ok"
            except Exception:
                return JSONResponse({"status": "degraded", "database": "unavailable", "demo": demo}, status_code=503)
        return JSONResponse(status)

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
            push_sender=push_sender, telegram_bot=telegram_bot,
        )

    if request_service is not None and require_session is not None:
        from .student_requests.router import register_request_routes

        register_request_routes(app, request_service)

    # Feature modules (study, documents, assistant, ...) register their routes
    # once the session dependency exists and before the SPA catch-all.
    if require_session is not None:
        for register in modules:
            register(app)

    if web_dist is not None:
        from .web import register_web

        register_web(app, web_dist)

    return app
