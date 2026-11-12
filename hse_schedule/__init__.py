"""HSE timetable parsing and personal student schedule integration."""

from .models import Group, Lesson
from .parser import parse_groups, parse_lessons

__all__ = ["Group", "Lesson", "parse_groups", "parse_lessons"]
