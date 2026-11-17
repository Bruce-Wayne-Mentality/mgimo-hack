"""Requests and certificates (module C4): catalogue, requests, history, comments.

Tables follow section 8: request_types, requests, request_events,
request_comments. request_counters backs the human number ДК-2026-000123.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..accounts.models import Student, User
from ..db import Base, JSONType, UTCDateTime, utcnow, uuid7

STATUSES = ("submitted", "in_review", "needs_info", "ready", "rejected", "cancelled")
_STATUS_SQL = ", ".join(f"'{status}'" for status in STATUSES)


class RequestType(Base):
    __tablename__ = "request_types"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    result: Mapped[str] = mapped_column(String(200), default="")
    # Business days; 0 means the system issues the result immediately (K2).
    sla_days: Mapped[int] = mapped_column(Integer, default=2)
    auto_issue: Mapped[bool] = mapped_column(Boolean, default=False)
    # Form fields: [{"name","label","kind","required","options","max_length","min","max","hint"}]
    fields: Mapped[list] = mapped_column(JSONType, default=list)
    sort: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint("sla_days >= 0", name="sla_non_negative"),)


class StudentRequest(Base):
    __tablename__ = "requests"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    number: Mapped[str] = mapped_column(String(24), unique=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    type_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("request_types.id", ondelete="RESTRICT"), index=True)
    status: Mapped[str] = mapped_column(String(16), default="submitted")
    payload: Mapped[dict] = mapped_column(JSONType, default=dict)
    idempotency_key: Mapped[str | None] = mapped_column(String(64), nullable=True)
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    result_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)

    type: Mapped[RequestType] = relationship(lazy="joined")
    student: Mapped[Student] = relationship(lazy="joined")
    events: Mapped[list[RequestEvent]] = relationship(
        back_populates="request", order_by="RequestEvent.at", lazy="selectin", cascade="all, delete-orphan"
    )
    comments: Mapped[list[RequestComment]] = relationship(
        back_populates="request", order_by="RequestComment.created_at", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        CheckConstraint(f"status IN ({_STATUS_SQL})", name="status_known"),
        UniqueConstraint("student_id", "idempotency_key", name="uq_requests_student_idempotency"),
        Index("ix_requests_student_created", "student_id", "created_at"),
        Index("ix_requests_status_due", "status", "due_at"),
    )


class RequestEvent(Base):
    """Status history. actor_id is NULL for transitions made by the system."""

    __tablename__ = "request_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16))
    actor_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)

    request: Mapped[StudentRequest] = relationship(back_populates="events")


class RequestComment(Base):
    __tablename__ = "request_comments"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    body: Mapped[str] = mapped_column(Text)
    # Internal notes are visible to staff only (section 10.2).
    internal: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    request: Mapped[StudentRequest] = relationship(back_populates="comments")
    author: Mapped[User | None] = relationship(lazy="joined")


class RequestCounter(Base):
    """Per-year sequence for request numbers; incremented inside the creating transaction."""

    __tablename__ = "request_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    value: Mapped[int] = mapped_column(Integer, default=0)
