"""Who may see which request (section 10.2). The only place with these rules.

- student: only own requests;
- staff: students of their own faculty and request types in their scopes;
- admin: everything.
"""

from __future__ import annotations

from sqlalchemy import false

from ..accounts.models import User
from .models import StudentRequest


def is_staff(user: User) -> bool:
    return user.is_active and user.role in ("staff", "admin")


def can_view_request(user: User, request: StudentRequest) -> bool:
    if not user.is_active:
        return False
    if user.role == "student":
        return user.student is not None and request.student_id == user.student.id
    if user.role == "admin":
        return True
    if user.role == "staff" and user.staff is not None:
        same_faculty = user.staff.faculty_id is not None and request.student.group.faculty_id == user.staff.faculty_id
        return same_faculty and request.type.code in (user.staff.scopes or [])
    return False


def scope_query(user: User, query, group_model, type_model):
    """Restrict a staff queue query to what can_view_request would allow."""
    if user.role == "admin":
        return query
    staff = user.staff
    if staff is None or staff.faculty_id is None:
        return query.where(false())
    return query.where(group_model.faculty_id == staff.faculty_id, type_model.code.in_(staff.scopes or []))
