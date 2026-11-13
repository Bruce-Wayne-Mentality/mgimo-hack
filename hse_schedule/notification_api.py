"""Authenticated bell, delivery preferences and notification channel enrollment."""

from __future__ import annotations

import re
import secrets
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException, Query, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr


class PreferenceUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: StrictBool


class PushSubscription(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: StrictStr = Field(max_length=2048)
    keys: dict[str, StrictStr]
    expirationTime: int | float | None = Field(default=None, ge=0)


class PushEndpoint(BaseModel):
    model_config = ConfigDict(extra="forbid")
    endpoint: StrictStr = Field(max_length=2048)


def register_notification_routes(
    app,
    service,
    store,
    authenticated_email,
    *,
    push_sender=None,
    telegram_bot=None,
) -> None:
    """Attach personal notification APIs using the host's verified identity."""

    def account(email: str = Depends(authenticated_email)) -> str:
        return service.directory.get(email).email

    @app.get("/api/me/notification-settings")
    def notification_settings(email: str = Depends(account)) -> dict:
        return store.get_settings(email)

    @app.patch("/api/me/notification-settings")
    def update_notification_settings(
        body: PreferenceUpdate, email: str = Depends(account)
    ) -> dict:
        return store.set_settings(email, body.enabled)

    @app.get("/api/me/notifications")
    def notifications(
        limit: int = Query(default=50, ge=1, le=100),
        before: int | None = Query(default=None, ge=1),
        unread_only: bool = False,
        email: str = Depends(account),
    ) -> dict:
        return store.list_notifications(
            email, limit=limit, before=before, unread_only=unread_only
        )

    # Register the fixed route before the parameterized notification route.
    @app.post("/api/me/notifications/read-all")
    def read_all_notifications(email: str = Depends(account)) -> dict:
        return {"updated": store.mark_all_read(email, datetime.now(timezone.utc))}

    @app.post("/api/me/notifications/{notification_id}/read")
    def read_notification(notification_id: int, email: str = Depends(account)) -> dict:
        if notification_id < 1 or not store.mark_read(
            email, notification_id, datetime.now(timezone.utc)
        ):
            raise HTTPException(status_code=404, detail="Уведомление не найдено.")
        return {"read": True}

    @app.get("/api/push/public-key")
    def push_public_key() -> dict:
        if push_sender is None:
            raise HTTPException(status_code=503, detail="Браузерные уведомления пока не настроены.")
        return {"public_key": push_sender.public_key}

    @app.post("/api/me/push-subscriptions", status_code=201)
    def add_push_subscription(
        body: PushSubscription, email: str = Depends(account)
    ) -> dict:
        from .push import validate_subscription

        if push_sender is None:
            raise HTTPException(status_code=503, detail="Браузерные уведомления пока не настроены.")
        try:
            subscription = validate_subscription(body.model_dump(exclude={"expirationTime"}))
        except ValueError as error:
            raise HTTPException(status_code=422, detail="Некорректная подписка браузера.") from error
        store.add_subscription(email, subscription, datetime.now(timezone.utc))
        return {"subscribed": True}

    @app.delete("/api/me/push-subscriptions", status_code=204)
    def remove_push_subscription(
        body: PushEndpoint, email: str = Depends(account)
    ) -> Response:
        store.remove_subscription(email, body.endpoint)
        return Response(status_code=204)

    @app.get("/api/me/telegram")
    def telegram_status(email: str = Depends(account)) -> dict:
        return store.telegram_status(email)

    @app.post("/api/me/telegram/link")
    def create_telegram_link(email: str = Depends(account)) -> dict:
        from .push import ChannelDeliveryError

        if telegram_bot is None:
            raise HTTPException(status_code=503, detail="Telegram-бот пока не настроен.")
        try:
            username = telegram_bot.get_username()
        except ChannelDeliveryError as error:
            raise HTTPException(status_code=503, detail="Telegram-бот временно недоступен.") from error
        if not isinstance(username, str) or not re.fullmatch(r"[A-Za-z0-9_]{5,32}", username):
            raise HTTPException(status_code=503, detail="Telegram-бот временно недоступен.")
        token = secrets.token_urlsafe(24)
        expires = datetime.now(timezone.utc) + timedelta(minutes=10)
        store.create_telegram_link(email, token, expires)
        return {
            "deep_link": f"https://t.me/{username}?start={token}",
            "expires_at": expires.isoformat(),
        }

    @app.delete("/api/me/telegram", status_code=204)
    def unlink_telegram(email: str = Depends(account)) -> Response:
        store.unlink_telegram(email)
        return Response(status_code=204)
