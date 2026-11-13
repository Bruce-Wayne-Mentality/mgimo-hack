"""HTTP endpoints for sign-in, sessions and the read-only profile (C1).

Error bodies follow section 9.1: {"error": {"code", "message", "fields"?}}.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from fastapi import Depends, FastAPI, Request, Response
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr

from . import policy
from .security import PASSWORD_MAX_LENGTH, csrf_matches, csrf_token
from .service import AuthError, AuthService, CurrentSession, LoginLocked, PasswordRejected

SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})
CSRF_HEADER = "X-CSRF-Token"

STUDY_FORM_LABELS = {"full_time": "Очная", "part_time": "Очно-заочная", "distance": "Заочная"}
STATUS_LABELS = {
    "active": "Обучается",
    "academic_leave": "Академический отпуск",
    "expelled": "Отчислен",
    "graduated": "Выпускник",
}
ROLE_LABELS = {"student": "Студент", "staff": "Сотрудник деканата", "admin": "Администратор"}


@dataclass(frozen=True)
class AuthSettings:
    secret: bytes
    cookie_secure: bool = True
    demo: bool = False

    @property
    def cookie_name(self) -> str:
        # The __Host- prefix pins the cookie to this host, path "/" and HTTPS.
        return "__Host-session" if self.cookie_secure else "session"


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, *, fields: dict | None = None,
                 headers: dict | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.fields = fields
        self.headers = headers


def error_response(status: int, code: str, message: str, *, fields: dict | None = None,
                   headers: dict | None = None) -> JSONResponse:
    body: dict = {"code": code, "message": message}
    if fields:
        body["fields"] = fields
    return JSONResponse(status_code=status, content={"error": body}, headers=headers)


class LoginBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    login: StrictStr = Field(min_length=1, max_length=64)
    password: StrictStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    remember: StrictBool = False


class PasswordBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    current_password: StrictStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)
    new_password: StrictStr = Field(min_length=1, max_length=PASSWORD_MAX_LENGTH)


FIELD_MESSAGES = {
    "login": "Введите логин.",
    "password": "Введите пароль.",
    "current_password": "Введите текущий пароль.",
    "new_password": "Введите новый пароль.",
}


def user_payload(user) -> dict:
    return {
        "id": str(user.id),
        "login": user.login,
        "role": user.role,
        "role_label": ROLE_LABELS.get(user.role, user.role),
        "display_name": user.display_name,
    }


def profile_payload(user) -> dict:
    if user.role == "student" and user.student is not None:
        student = user.student
        if not policy.can_view_student_profile(user, student):
            raise ApiError(404, "not_found", "Профиль не найден.")
        group = student.group
        return {
            "kind": "student",
            "full_name": student.full_name,
            "faculty": group.faculty.title,
            "program": {"code": group.program_code, "title": group.program_title},
            "course": group.course,
            "group": group.code,
            "study_form": STUDY_FORM_LABELS.get(student.study_form, student.study_form),
            "status": STATUS_LABELS.get(student.status, student.status),
            "record_book_no": student.record_book_no,
            "contacts": {"email": student.email, "phone": student.phone},
        }
    if user.staff is not None:
        staff = user.staff
        return {
            "kind": "staff",
            "full_name": staff.full_name,
            "position": staff.position,
            "faculty": staff.faculty.title if staff.faculty else None,
            "role": ROLE_LABELS.get(user.role, user.role),
        }
    return {"kind": user.role, "full_name": user.display_name, "role": ROLE_LABELS.get(user.role, user.role)}


def register_auth_routes(app: FastAPI, auth: AuthService, settings: AuthSettings, *, demo_accounts=()):
    """Attach /api/auth/* and /api/me/profile; returns the session dependency."""

    @app.exception_handler(ApiError)
    async def api_error(_request: Request, error: ApiError):
        return error_response(error.status, error.code, error.message, fields=error.fields,
                              headers=error.headers)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        if not request.url.path.startswith("/api/auth/"):
            return await request_validation_exception_handler(request, error)
        fields = {}
        for item in error.errors():
            location = [str(part) for part in item.get("loc", ()) if part != "body"]
            name = location[0] if location else "body"
            fields.setdefault(name, FIELD_MESSAGES.get(name, "Проверьте значение поля."))
        return error_response(422, "validation_failed", "Проверьте заполнение формы.", fields=fields)

    def set_session_cookie(response: Response, token: str, max_age: int | None) -> None:
        response.set_cookie(
            settings.cookie_name, token, max_age=max_age, path="/",
            httponly=True, secure=settings.cookie_secure, samesite="lax",
        )

    def clear_session_cookie(response: Response) -> None:
        response.delete_cookie(
            settings.cookie_name, path="/", httponly=True, secure=settings.cookie_secure, samesite="lax"
        )

    async def optional_session(request: Request) -> CurrentSession | None:
        return await auth.resolve(request.cookies.get(settings.cookie_name))

    async def require_session(request: Request) -> CurrentSession:
        current = await optional_session(request)
        if current is None:
            raise ApiError(401, "unauthorized", "Войдите в аккаунт, чтобы продолжить.")
        if request.method not in SAFE_METHODS and not csrf_matches(
            settings.secret, current.token, request.headers.get(CSRF_HEADER)
        ):
            raise ApiError(403, "csrf_failed", "Сессия устарела. Обновите страницу и повторите действие.")
        return current

    app.state.optional_session = optional_session
    app.state.require_session = require_session

    @app.post("/api/auth/login", tags=["auth"])
    async def login(body: LoginBody, request: Request, response: Response) -> dict:
        previous = await optional_session(request)
        try:
            result = await auth.login(
                body.login, body.password,
                ip=request.client.host if request.client else "unknown",
                user_agent=request.headers.get("user-agent"),
                remember=body.remember,
            )
        except LoginLocked as locked:
            minutes = max(1, math.ceil(locked.retry_after.total_seconds() / 60))
            raise ApiError(
                429, "too_many_attempts",
                f"Слишком много неудачных попыток. Повторите вход через {minutes} мин.",
                headers={"Retry-After": str(int(locked.retry_after.total_seconds()) or 1)},
            ) from None
        except AuthError:
            raise ApiError(401, "invalid_credentials", "Неверный логин или пароль.") from None
        if previous is not None:
            await auth.logout(previous)
        set_session_cookie(response, result.token, result.max_age)
        return {"user": user_payload(result.user), "csrf_token": csrf_token(settings.secret, result.token)}

    @app.get("/api/auth/me", tags=["auth"])
    async def me(current: CurrentSession = Depends(require_session)) -> dict:
        return {"user": user_payload(current.user), "csrf_token": csrf_token(settings.secret, current.token)}

    @app.post("/api/auth/logout", status_code=204, tags=["auth"])
    async def logout(response: Response, current: CurrentSession = Depends(require_session)) -> Response:
        await auth.logout(current)
        clear_session_cookie(response)
        response.status_code = 204
        return response

    @app.post("/api/auth/logout-all", status_code=204, tags=["auth"])
    async def logout_all(response: Response, current: CurrentSession = Depends(require_session)) -> Response:
        await auth.logout_everywhere(current)
        clear_session_cookie(response)
        response.status_code = 204
        return response

    @app.post("/api/auth/password", status_code=204, tags=["auth"])
    async def change_password(body: PasswordBody, current: CurrentSession = Depends(require_session)) -> Response:
        try:
            await auth.change_password(current, body.current_password, body.new_password)
        except PasswordRejected as rejected:
            raise ApiError(422, "validation_failed", rejected.message,
                           fields={rejected.field: rejected.message}) from None
        return Response(status_code=204)

    @app.get("/api/auth/demo-accounts", tags=["auth"])
    async def demo_account_list() -> dict:
        if not settings.demo:
            raise ApiError(404, "not_found", "Тестовые аккаунты доступны только в демо-режиме.")
        return {"accounts": [dict(account) for account in demo_accounts]}

    @app.get("/api/me/profile", tags=["profile"])
    async def profile(current: CurrentSession = Depends(require_session)) -> dict:
        return profile_payload(current.user)

    return require_session
