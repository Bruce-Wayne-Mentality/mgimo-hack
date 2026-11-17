"""Attachment tables.

Files live on disk under a random uuid (storage_key), outside the public static
directory; the database keeps the cleaned original name and the metadata.
A row without a message is staged: uploaded and checked, not sent yet.

Red button attachments never name the student: the owner is author_ref (the
same HMAC the complaint uses). Their names are encrypted like their content.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Integer, LargeBinary, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, UTCDateTime, utcnow, uuid7

KIND_CHECK = "kind IN ('pdf', 'docx', 'jpeg', 'png')"


class RequestAttachment(Base):
    __tablename__ = "request_attachments"
    __table_args__ = (CheckConstraint(KIND_CHECK, name="kind_known"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), index=True)
    comment_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("request_comments.id", ondelete="CASCADE"), nullable=True, index=True)
    uploader_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name: Mapped[str] = mapped_column(String(160))
    kind: Mapped[str] = mapped_column(String(8))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(36), unique=True)
    sha256: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    attached_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ComplaintAttachment(Base):
    __tablename__ = "complaint_attachments"
    __table_args__ = (
        CheckConstraint(KIND_CHECK, name="kind_known"),
        CheckConstraint("check_status IN ('ok', 'blocked', 'unverified', 'skipped')", name="check_known"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    complaint_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("complaints.id", ondelete="CASCADE"), nullable=True, index=True)
    message_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("complaint_messages.id", ondelete="CASCADE"), nullable=True, index=True)
    owner_ref: Mapped[str] = mapped_column(String(64), index=True)  # author_ref of the student, or the staff user id
    from_role: Mapped[str] = mapped_column(String(16))  # student | staff | curator
    name_ct: Mapped[bytes] = mapped_column(LargeBinary)
    kind: Mapped[str] = mapped_column(String(8))
    mime: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(Integer)
    storage_key: Mapped[str] = mapped_column(String(36), unique=True)
    key_id: Mapped[str | None] = mapped_column(String(8), nullable=True)  # set while sealed with the day key (before acceptance)
    check_status: Mapped[str] = mapped_column(String(16))  # ok | blocked | unverified | skipped (staff files)
    check_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True, index=True)  # staged files only
    attached_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
