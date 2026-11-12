"""Errors callers can handle without depending on HTTP implementation details."""


class ScheduleError(Exception):
    """Base error for schedule operations."""


class InvalidPayload(ScheduleError):
    """The upstream response does not match the timetable schema."""


class SourceUnavailable(ScheduleError):
    """The timetable source cannot currently be reached or accessed."""


class UnknownStudent(ScheduleError):
    """No enrollment is configured for this account."""


class ConfigurationError(ScheduleError):
    """The roster or source configuration is invalid."""
