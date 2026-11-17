"""Study records (section 8, «Учёба» and «Риск»): disciplines, checkpoints,
scores with their change history, attendance, past results and risk snapshots.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType, UTCDateTime, utcnow, uuid7

CONTROL_FORMS = ("exam", "credit", "diff_credit", "coursework")
CONTROL_LABELS = {
    "exam": "Экзамен",
    "credit": "Зачёт",
    "diff_credit": "Дифференцированный зачёт",
    "coursework": "Курсовая работа",
}


class Discipline(Base):
    __tablename__ = "disciplines"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="CASCADE"), index=True)
    semester: Mapped[str] = mapped_column(String(32))
    code: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    teacher_name: Mapped[str] = mapped_column(String(200))
    control_form: Mapped[str] = mapped_column(String(16))
    credits: Mapped[int] = mapped_column(Integer)
    admission_threshold: Mapped[int] = mapped_column(Integer, default=40)
    final_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    final_room: Mapped[str | None] = mapped_column(String(64), nullable=True)

    checkpoints: Mapped[list[Checkpoint]] = relationship(
        back_populates="discipline", order_by="Checkpoint.sort", lazy="selectin", cascade="all, delete-orphan"
    )

    __table_args__ = (
        UniqueConstraint("group_id", "semester", "code", name="uq_disciplines_group_semester_code"),
        CheckConstraint("control_form IN ('exam', 'credit', 'diff_credit', 'coursework')", name="control_form_known"),
        CheckConstraint("admission_threshold BETWEEN 0 AND 100", name="threshold_range"),
    )


class Checkpoint(Base):
    __tablename__ = "checkpoints"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    discipline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disciplines.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    weight: Mapped[int] = mapped_column(Integer)
    max_score: Mapped[int] = mapped_column(Integer)
    due_on: Mapped[date | None] = mapped_column(Date, nullable=True)
    critical: Mapped[bool] = mapped_column(Boolean, default=False)
    is_final: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[int] = mapped_column(Integer, default=0)

    discipline: Mapped[Discipline] = relationship(back_populates="checkpoints")

    __table_args__ = (
        CheckConstraint("weight BETWEEN 0 AND 100", name="weight_range"),
        CheckConstraint("max_score > 0", name="max_positive"),
    )


class Grade(Base):
    __tablename__ = "grades"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checkpoints.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float)
    graded_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    graded_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    __table_args__ = (
        UniqueConstraint("student_id", "checkpoint_id", name="uq_grades_student_checkpoint"),
        CheckConstraint("score >= 0", name="score_non_negative"),
    )


class GradeChange(Base):
    """FR-GRD-2: who changed a score and when. Never updated, only appended."""

    __tablename__ = "grade_changes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    checkpoint_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("checkpoints.id", ondelete="CASCADE"))
    old_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    new_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    changed_by: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    changed_by_name: Mapped[str] = mapped_column(String(200))
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (Index("ix_grade_changes_student_checkpoint", "student_id", "checkpoint_id"),)


class Attendance(Base):
    """Attendance per discipline as counters (lessons come from the timetable source)."""

    __tablename__ = "attendance"

    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    discipline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disciplines.id", ondelete="CASCADE"), primary_key=True)
    attended: Mapped[int] = mapped_column(Integer, default=0)
    total: Mapped[int] = mapped_column(Integer, default=0)

    __table_args__ = (CheckConstraint("attended >= 0 AND attended <= total", name="attended_range"),)


class PastResult(Base):
    """Closed disciplines of previous semesters (FR-GRD-4: average and dynamics)."""

    __tablename__ = "past_results"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    semester_no: Mapped[int] = mapped_column(Integer)
    semester: Mapped[str] = mapped_column(String(32))
    title: Mapped[str] = mapped_column(String(200))
    control_form: Mapped[str] = mapped_column(String(16))
    credits: Mapped[int] = mapped_column(Integer)
    mark: Mapped[int | None] = mapped_column(Integer, nullable=True)
    passed: Mapped[bool] = mapped_column(Boolean, default=True)

    __table_args__ = (CheckConstraint("mark IS NULL OR mark BETWEEN 2 AND 5", name="mark_range"),)


class RiskSnapshot(Base):
    """Traffic-light history (K1 → K5). A row is written when the level changes."""

    __tablename__ = "risk_snapshots"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"))
    discipline_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("disciplines.id", ondelete="CASCADE"))
    level: Mapped[str] = mapped_column(String(8))
    p: Mapped[float] = mapped_column(Float)
    w: Mapped[float] = mapped_column(Float)
    pace: Mapped[float | None] = mapped_column(Float, nullable=True)
    r: Mapped[float] = mapped_column(Float)
    reasons: Mapped[list] = mapped_column(JSONType, default=list)
    computed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        Index("ix_risk_snapshots_student_discipline", "student_id", "discipline_id", "computed_at"),
        CheckConstraint("level IN ('green', 'yellow', 'red', 'grey')", name="level_known"),
    )


class Nudge(Base):
    """K5: a proactive hint. dedup_key keeps one (rule, object) per day."""

    __tablename__ = "nudges"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), index=True)
    rule_code: Mapped[str] = mapped_column(String(32))
    dedup_key: Mapped[str] = mapped_column(String(160))
    title: Mapped[str] = mapped_column(String(200))
    text: Mapped[str] = mapped_column(Text)
    action: Mapped[dict] = mapped_column(JSONType, default=dict)
    state: Mapped[str] = mapped_column(String(16), default="new")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    __table_args__ = (
        UniqueConstraint("student_id", "dedup_key", name="uq_nudges_student_dedup"),
        CheckConstraint("state IN ('new', 'seen', 'done', 'dismissed')", name="state_known"),
    )


class NudgeMute(Base):
    """«Не показывать такое»: the student switched a rule off."""

    __tablename__ = "nudge_mutes"

    student_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("students.id", ondelete="CASCADE"), primary_key=True)
    rule_code: Mapped[str] = mapped_column(String(32), primary_key=True)
