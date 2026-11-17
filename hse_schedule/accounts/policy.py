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


def can_manage_kb(user: User) -> bool:
    """Assistant knowledge base: see the queue of unanswered questions and publish answers."""
    return user.is_active and user.role in ("staff", "admin")


# ---- attachments in chats (one place for these rules) --------------------------------------

def can_open_request_attachment(user: User, *, sees_request: bool, internal: bool, uploader_id=None, sent: bool = True) -> bool:
    """A request chat's file is open to whoever sees that chat message.

    sees_request comes from student_requests.policy.can_view_request (the author, staff of the
    student's faculty with this request type in scope, admin). Internal notes stay staff-only.
    A file not sent yet is open to its uploader only.
    """
    if not user.is_active or not sees_request:
        return False
    if not sent:
        return uploader_id == user.id
    return not (internal and user.role == "student")


def can_open_complaint_attachment(user: User, *, role: str | None, is_author: bool, is_assignee: bool,
                                  conflict: bool, sent: bool = True, is_uploader: bool = False) -> bool:
    """A red button file: the author, the assigned employee and the curator — nobody else.

    role is the red button role (curator | staff | None). conflict: the employee is the subject
    of the complaint. A file not sent yet is open to its uploader only.
    """
    if not user.is_active:
        return False
    if not sent:
        return is_uploader
    if is_author:
        return True
    if conflict:
        return False
    return role == "curator" or (role is not None and is_assignee)
