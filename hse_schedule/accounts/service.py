"""Login, sessions, brute-force protection and password changes (FR-AUTH-1..5)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from ..db import Database, utcnow
from . import security
from .models import AuditLog, LoginThrottle, User, UserSession

SESSION_IDLE = timedelta(hours=12)
SESSION_REMEMBER = timedelta(days=30)
TOUCH_EVERY = timedelta(minutes=1)

PAIR_LIMIT = 5  # FR-AUTH-3: 5 failures per "login + IP" within the window
IP_LIMIT = 30  # spraying many logins from one address
THROTTLE_WINDOW = timedelta(minutes=15)
LOCK_FOR = timedelta(minutes=15)


class AuthError(Exception):
    """Login failed; the message is identical for unknown login and bad password."""


class LoginLocked(Exception):
    def __init__(self, retry_after: timedelta) -> None:
        super().__init__("locked")
        self.retry_after = retry_after


class PasswordRejected(Exception):
    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


@dataclass(frozen=True)
class LoginResult:
    user: User
    token: str
    remember: bool
    max_age: int | None


@dataclass(frozen=True)
class CurrentSession:
    user: User
    session_id: uuid.UUID
    token: str


def normalize_login(value: str) -> str:
    return value.strip().casefold()


class AuthService:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utcnow) -> None:
        self.database = database
        self.clock = clock

    # ---- login -----------------------------------------------------------

    async def login(
        self,
        login: str,
        password: str,
        *,
        ip: str,
        user_agent: str | None,
        remember: bool,
    ) -> LoginResult:
        now = self.clock()
        login = normalize_login(login)
        pair_key = security.throttle_key("pair", login, ip)
        ip_key = security.throttle_key("ip", ip)
        async with self.database.session() as db:
            for key in (pair_key, ip_key):
                retry = await self._locked_for(db, key, now)
                if retry is not None:
                    raise LoginLocked(retry)

            user = await db.scalar(select(User).where(func.lower(User.login) == login))
            valid = security.verify_password(user.password_hash if user else None, password)
            if not valid or user is None or not user.is_active:
                pair_locked = await self._register_failure(db, pair_key, PAIR_LIMIT, now)
                ip_locked = await self._register_failure(db, ip_key, IP_LIMIT, now)
                db.add(AuditLog(
                    actor_id=user.id if user else None,
                    action="auth.login_locked" if pair_locked or ip_locked else "auth.login_failed",
                    at=now,
                ))
                await db.commit()
                if pair_locked or ip_locked:
                    raise LoginLocked(LOCK_FOR)
                raise AuthError()

            if security.needs_rehash(user.password_hash):
                user.password_hash = security.hash_password(password)
            await db.execute(delete(LoginThrottle).where(LoginThrottle.key_hash == pair_key))
            await db.execute(delete(UserSession).where(UserSession.expires_at <= now))
            token = security.new_session_token()
            lifetime = SESSION_REMEMBER if remember else SESSION_IDLE
            session = UserSession(
                user_id=user.id,
                token_hash=security.token_hash(token),
                remember=remember,
                created_at=now,
                last_seen_at=now,
                expires_at=now + lifetime,
                user_agent=(user_agent or "")[:255] or None,
            )
            db.add(session)
            db.add(AuditLog(actor_id=user.id, action="auth.login", object_type="session",
                            object_id=str(session.id), at=now))
            await db.commit()
            return LoginResult(
                user=user,
                token=token,
                remember=remember,
                max_age=int(SESSION_REMEMBER.total_seconds()) if remember else None,
            )

    async def _locked_for(self, db: AsyncSession, key: str, now: datetime) -> timedelta | None:
        row = await db.get(LoginThrottle, key)
        if row is not None and row.locked_until is not None and row.locked_until > now:
            return row.locked_until - now
        return None

    async def _register_failure(self, db: AsyncSession, key: str, limit: int, now: datetime) -> bool:
        row = await db.get(LoginThrottle, key)
        if row is None:
            row = LoginThrottle(key_hash=key, failures=0, window_started_at=now)
            db.add(row)
        expired_window = now - row.window_started_at >= THROTTLE_WINDOW
        expired_lock = row.locked_until is not None and row.locked_until <= now
        if expired_window or expired_lock:
            row.failures = 0
            row.window_started_at = now
            row.locked_until = None
        row.failures += 1
        if row.failures >= limit:
            row.locked_until = now + LOCK_FOR
            return True
        return False

    # ---- sessions --------------------------------------------------------

    async def resolve(self, token: str | None) -> CurrentSession | None:
        if not token or len(token) > 128:
            return None
        now = self.clock()
        async with self.database.session() as db:
            session = await db.scalar(
                select(UserSession).where(UserSession.token_hash == security.token_hash(token))
            )
            if session is None:
                return None
            if session.expires_at <= now or not session.user.is_active:
                await db.delete(session)
                await db.commit()
                return None
            if now - session.last_seen_at >= TOUCH_EVERY:
                session.last_seen_at = now
                session.expires_at = now + (SESSION_REMEMBER if session.remember else SESSION_IDLE)
                await db.commit()
            return CurrentSession(user=session.user, session_id=session.id, token=token)

    async def logout(self, current: CurrentSession) -> None:
        async with self.database.session() as db:
            await db.execute(delete(UserSession).where(UserSession.id == current.session_id))
            db.add(AuditLog(actor_id=current.user.id, action="auth.logout", at=self.clock()))
            await db.commit()

    async def logout_everywhere(self, current: CurrentSession) -> int:
        async with self.database.session() as db:
            result = await db.execute(delete(UserSession).where(UserSession.user_id == current.user.id))
            db.add(AuditLog(actor_id=current.user.id, action="auth.logout_all", at=self.clock()))
            await db.commit()
            return result.rowcount or 0

    # ---- password --------------------------------------------------------

    async def change_password(self, current: CurrentSession, old_password: str, new_password: str) -> None:
        if not (security.PASSWORD_MIN_LENGTH <= len(new_password) <= security.PASSWORD_MAX_LENGTH):
            raise PasswordRejected(
                "new_password",
                f"Новый пароль должен содержать от {security.PASSWORD_MIN_LENGTH} "
                f"до {security.PASSWORD_MAX_LENGTH} символов.",
            )
        if not new_password.strip():
            raise PasswordRejected("new_password", "Пароль не может состоять из пробелов.")
        now = self.clock()
        async with self.database.session() as db:
            user = await db.get(User, current.user.id)
            if user is None or not security.verify_password(user.password_hash, old_password):
                raise PasswordRejected("current_password", "Текущий пароль указан неверно.")
            if security.verify_password(user.password_hash, new_password):
                raise PasswordRejected("new_password", "Новый пароль совпадает с текущим.")
            user.password_hash = security.hash_password(new_password)
            user.password_changed_at = now
            # FR-AUTH-4: a password change ends every other session.
            await db.execute(
                delete(UserSession).where(
                    UserSession.user_id == user.id, UserSession.id != current.session_id
                )
            )
            db.add(AuditLog(actor_id=user.id, action="auth.password_changed", at=now))
            await db.commit()

    # ---- profile ---------------------------------------------------------

    async def load_user(self, user_id: uuid.UUID) -> User | None:
        async with self.database.session() as db:
            return await db.get(User, user_id)
