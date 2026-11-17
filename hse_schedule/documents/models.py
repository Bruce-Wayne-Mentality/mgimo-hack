"""Issued documents (K2): the PDF itself, its public id and the demo signature."""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, LargeBinary, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from ..db import Base, UTCDateTime, utcnow, uuid7


class Document(Base):
    __tablename__ = "documents"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("requests.id", ondelete="CASCADE"), unique=True)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    public_id: Mapped[str] = mapped_column(String(16), unique=True)
    title: Mapped[str] = mapped_column(String(200))
    number: Mapped[str] = mapped_column(String(32))
    holder_initials: Mapped[str] = mapped_column(String(16))
    sha256: Mapped[str] = mapped_column(String(64))
    signature: Mapped[str] = mapped_column(String(64))
    issued_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    revoke_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    pdf: Mapped[bytes] = mapped_column(LargeBinary)
