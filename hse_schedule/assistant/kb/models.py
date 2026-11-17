"""Tables of the knowledge base.

Vectors are float32 bytes in a LargeBinary column, so the same schema works on
PostgreSQL and SQLite without pgvector; cosine similarity runs in numpy.
content_hash lets re-indexing touch only fragments whose text changed.
KbGap keeps only the masked question: no student id, no name, no contacts.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, Float, ForeignKey, Integer, LargeBinary, String, Text, UniqueConstraint, Uuid
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ...db import Base, UTCDateTime, utcnow, uuid7


class KbDocument(Base):
    __tablename__ = "kb_documents"
    __table_args__ = (
        CheckConstraint("kind IN ('regulation', 'portal')", name="kind_known"),
        CheckConstraint("status IN ('active', 'superseded', 'draft')", name="status_known"),
        CheckConstraint("audience IN ('all', 'foreign', 'bachelor', 'master')", name="audience_known"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    doc_id: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(300))
    kind: Mapped[str] = mapped_column(String(16))
    version: Mapped[str] = mapped_column(String(32))
    status: Mapped[str] = mapped_column(String(16), index=True)
    effective_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    priority: Mapped[int] = mapped_column(Integer, default=2)
    audience: Mapped[str] = mapped_column(String(16), default="all")
    source_path: Mapped[str] = mapped_column(String(300))
    content_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, onupdate=utcnow)

    # The ORM deletes fragments itself (SQLite runs without foreign key enforcement);
    # ON DELETE CASCADE in the schema covers raw deletes on PostgreSQL.
    chunks: Mapped[list[KbChunk]] = relationship(back_populates="document", cascade="all, delete-orphan",
                                                  order_by="KbChunk.ord")


class KbChunk(Base):
    __tablename__ = "kb_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "ord"),
        CheckConstraint("kind IN ('clause', 'table', 'faq', 'paragraph')", name="kind_known"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("kb_documents.id", ondelete="CASCADE"), index=True)
    ord: Mapped[int] = mapped_column(Integer)
    section_path: Mapped[str] = mapped_column(String(300))
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    kind: Mapped[str] = mapped_column(String(16))
    text: Mapped[str] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer)
    content_hash: Mapped[str] = mapped_column(String(64))
    embedding: Mapped[bytes | None] = mapped_column(LargeBinary, nullable=True)
    embedding_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    document: Mapped[KbDocument] = relationship(back_populates="chunks")


class KbGap(Base):
    __tablename__ = "kb_gaps"
    __table_args__ = (CheckConstraint("status IN ('open', 'answered', 'rejected')", name="status_known"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    question_masked: Mapped[str] = mapped_column(Text)
    top_score: Mapped[float] = mapped_column(Float, default=0.0)
    top_chunk_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="open", index=True)
    answer_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    answered_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    answered_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
