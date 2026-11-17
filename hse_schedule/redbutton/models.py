"""Red button tables (spec, section 7). Texts are stored only encrypted.

complaints              the registry: final text sealed with its own DEK, AI labels
complaint_authors       complaint ↔ student for named and confidential complaints (curator only)
complaint_messages      correspondence, sealed with the complaint's DEK
complaint_events        status history without text
moderation_buffer       raw attempts of a session, AES-GCM with the key of the day
moderation_events       verdicts, scores, HMAC of the text — never the text
complaint_counters      КК-YYYY-NNNN numbering
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, JSONType, UTCDateTime, utcnow, uuid7

STATUSES = ("MODERATION", "NEW", "IN_PROGRESS", "NEED_INFO", "ANSWERED", "ESCALATED", "CLOSED", "WITHDRAWN", "RETURNED")
PRIVACY = ("named", "confidential", "anonymous")
TYPES = ("unfair", "problem", "suggestion", "thanks")
CATEGORIES = ("grades", "schedule", "teacher_conduct", "dean_office", "documents", "scholarship_payment", "dormitory",
              "infrastructure", "other")


class Complaint(Base):
    __tablename__ = "complaints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    number: Mapped[str] = mapped_column(String(32), unique=True)
    type: Mapped[str] = mapped_column(String(16))
    category: Mapped[str] = mapped_column(String(32))
    category_source: Mapped[str] = mapped_column(String(8), default="student")
    subject_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    # Who the complaint is about, when that person has an account: never sees or reviews it.
    subject_user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    link_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    link_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    link_label: Mapped[str | None] = mapped_column(String(200), nullable=True)
    title: Mapped[str] = mapped_column(String(120))
    title_source: Mapped[str] = mapped_column(String(8), default="system")
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    privacy: Mapped[str] = mapped_column(String(16))
    author_ref: Mapped[str] = mapped_column(String(64), index=True)
    desired_outcome: Mapped[str | None] = mapped_column(String(32), nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="NEW")
    priority: Mapped[int] = mapped_column(Integer, default=2)
    department: Mapped[str] = mapped_column(String(120))
    assignee_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    take_due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    answer_due_at: Mapped[datetime] = mapped_column(UTCDateTime)
    paused_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    taken_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    resolved_by_student: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    moderation_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    return_comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    flags: Mapped[list] = mapped_column(JSONType, default=list)
    ai: Mapped[dict] = mapped_column(JSONType, default=dict)
    stage2_state: Mapped[str] = mapped_column(String(12), default="pending")
    stage2_attempts: Mapped[int] = mapped_column(Integer, default=0)
    stage2_next_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    body_ct: Mapped[bytes] = mapped_column(LargeBinary)
    body_dek: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)

    __table_args__ = (
        CheckConstraint("status IN ('MODERATION', 'NEW', 'IN_PROGRESS', 'NEED_INFO', 'ANSWERED', 'ESCALATED', "
                        "'CLOSED', 'WITHDRAWN', 'RETURNED')", name="status_known"),
        CheckConstraint("privacy IN ('named', 'confidential', 'anonymous')", name="privacy_known"),
        CheckConstraint("type IN ('unfair', 'problem', 'suggestion', 'thanks')", name="type_known"),
        CheckConstraint("priority BETWEEN 1 AND 3", name="priority_range"),
        Index("ix_complaints_status_priority", "status", "priority", "answer_due_at"),
    )


class ComplaintAuthor(Base):
    """Only for named and confidential complaints; read by the curator role only."""

    __tablename__ = "complaint_authors"

    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)


class ComplaintMessage(Base):
    __tablename__ = "complaint_messages"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    from_role: Mapped[str] = mapped_column(String(16))  # student | staff | curator | system
    author_name: Mapped[str | None] = mapped_column(String(200), nullable=True)  # staff only, never the student
    kind: Mapped[str] = mapped_column(String(16), default="message")  # message | answer | need_info | feedback
    body_ct: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ComplaintEvent(Base):
    __tablename__ = "complaint_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    complaint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), index=True)
    from_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    to_status: Mapped[str] = mapped_column(String(16))
    actor_role: Mapped[str] = mapped_column(String(16))
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ModerationBuffer(Base):
    __tablename__ = "moderation_buffer"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    session_id: Mapped[uuid.UUID] = mapped_column(Uuid, index=True)
    author_ref: Mapped[str] = mapped_column(String(64))
    seq: Mapped[int] = mapped_column(Integer, default=1)
    state: Mapped[str] = mapped_column(String(16))
    verdict: Mapped[str] = mapped_column(String(16))
    attempts: Mapped[int] = mapped_column(Integer, default=1)
    form: Mapped[dict] = mapped_column(JSONType, default=dict)  # chosen type, category, link, privacy — no text
    key_id: Mapped[str] = mapped_column(String(8))
    nonce: Mapped[bytes] = mapped_column(LargeBinary)
    ct: Mapped[bytes] = mapped_column(LargeBinary)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)


class ModerationEvent(Base):
    __tablename__ = "moderation_events"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True, index=True)
    complaint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), nullable=True)
    stage: Mapped[int] = mapped_column(Integer)
    verdict: Mapped[str] = mapped_column(String(24))
    scores: Mapped[dict] = mapped_column(JSONType, default=dict)
    flags: Mapped[list] = mapped_column(JSONType, default=list)
    text_hmac: Mapped[str | None] = mapped_column(String(64), nullable=True)
    models: Mapped[dict] = mapped_column(JSONType, default=dict)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    tokens: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)


class ComplaintCounter(Base):
    __tablename__ = "complaint_counters"

    year: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    value: Mapped[int] = mapped_column(Integer, default=0)
