"""Single place that decides who may see which account object (section 10.2).

Endpoints never accept a student/user id from the client: the subject is
always the session owner. Staff and admin rules are added with their screens.
"""

from __future__ import annotations

from .models import Student, User


def can_view_student_profile(user: User, student: Student) -> bool:
    if user.role == "student":
        return student.user_id == user.id
    # Staff (own faculty) and admin access arrive together with S1.
    return False


def schedule_email(user: User) -> str | None:
    """Email that links the account to the timetable roster; students only."""
    if user.role == "student" and user.student is not None and user.is_active:
        return user.student.email
    return None
