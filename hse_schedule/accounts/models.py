"""Accounts, academic profiles, server sessions, login throttling and audit log.

Tables follow section 8 of the design document (users, students, staff,
faculties, groups, sessions, audit_log). login_throttle backs FR-AUTH-3.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, Index, Integer, String, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from ..db import Base, JSONType, UTCDateTime, utcnow, uuid7

ROLES = ("student", "staff", "admin")
STUDY_FORMS = ("full_time", "part_time", "distance")
STUDENT_STATUSES = ("active", "academic_leave", "expelled", "graduated")


class Faculty(Base):
    __tablename__ = "faculties"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    title: Mapped[str] = mapped_column(String(200))


class StudyGroup(Base):
    __tablename__ = "groups"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    faculty_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("faculties.id", ondelete="RESTRICT"), index=True)
    code: Mapped[str] = mapped_column(String(32), unique=True)
    course: Mapped[int] = mapped_column(Integer)
    program_code: Mapped[str] = mapped_column(String(16))
    program_title: Mapped[str] = mapped_column(String(200))

    faculty: Mapped[Faculty] = relationship(lazy="joined")

    __table_args__ = (CheckConstraint("course BETWEEN 1 AND 6", name="course_range"),)


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    login: Mapped[str] = mapped_column(String(64))
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[str] = mapped_column(String(16))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    password_changed_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)

    student: Mapped[Student | None] = relationship(back_populates="user", uselist=False, lazy="selectin")
    staff: Mapped[Staff | None] = relationship(back_populates="user", uselist=False, lazy="selectin")

    __table_args__ = (
        Index("uq_users_login_lower", func.lower(login), unique=True),
        CheckConstraint("role IN ('student', 'staff', 'admin')", name="role_known"),
    )

    @property
    def display_name(self) -> str:
        if self.student is not None:
            return self.student.full_name
        if self.staff is not None:
            return self.staff.full_name
        return self.login


class Student(Base):
    __tablename__ = "students"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    record_book_no: Mapped[str] = mapped_column(String(32), unique=True)
    group_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("groups.id", ondelete="RESTRICT"), index=True)
    study_form: Mapped[str] = mapped_column(String(16), default="full_time")
    status: Mapped[str] = mapped_column(String(16), default="active")
    # Contact data; the email also links the account to the timetable roster.
    email: Mapped[str] = mapped_column(String(254), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)

    user: Mapped[User] = relationship(back_populates="student")
    group: Mapped[StudyGroup] = relationship(lazy="joined")

    __table_args__ = (
        CheckConstraint("study_form IN ('full_time', 'part_time', 'distance')", name="study_form_known"),
        CheckConstraint(
            "status IN ('active', 'academic_leave', 'expelled', 'graduated')", name="status_known"
        ),
    )


class Staff(Base):
    __tablename__ = "staff"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    full_name: Mapped[str] = mapped_column(String(200))
    position: Mapped[str] = mapped_column(String(200))
    faculty_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("faculties.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    scopes: Mapped[list] = mapped_column(JSONType, default=list)

    user: Mapped[User] = relationship(back_populates="staff")
    faculty: Mapped[Faculty | None] = relationship(lazy="joined")


class UserSession(Base):
    """Server-side session. Only the SHA-256 of the cookie token is stored."""

    __tablename__ = "sessions"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    remember: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    user_agent: Mapped[str | None] = mapped_column(String(255), nullable=True)

    user: Mapped[User] = relationship(lazy="joined")


class LoginThrottle(Base):
    """Failed-login counters keyed by a hash of "login + IP" or of the IP alone."""

    __tablename__ = "login_throttle"

    key_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    failures: Mapped[int] = mapped_column(Integer, default=0)
    window_started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    locked_until: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(64))
    object_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    object_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    at: Mapped[datetime] = mapped_column(UTCDateTime, default=utcnow, index=True)
    meta: Mapped[dict] = mapped_column(JSONType, default=dict)
