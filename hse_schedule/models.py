"""Source-independent objects consumed by the personal account website."""

from dataclasses import asdict, dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Group:
    oid: str
    name: str


@dataclass(frozen=True, slots=True)
class LessonChange:
    """A deanery edit on top of the source timetable (FR-STF-5): «было → стало»."""

    kind: str  # moved | cancelled | room
    note: str | None = None
    was_starts_at: str | None = None
    was_ends_at: str | None = None
    was_room: str | None = None
    change_id: str | None = None


@dataclass(frozen=True, slots=True)
class Lesson:
    id: str
    date: date
    starts_at: datetime
    ends_at: datetime
    title: str
    kind: str | None
    teachers: tuple[str, ...]
    groups: tuple[Group, ...]
    subgroup: str | None
    room: str | None
    building: str | None
    links: tuple[str, ...]
    source_lesson_id: str | None
    change: LessonChange | None = None

    def to_dict(self) -> dict:
        result = asdict(self)
        result.update(
            date=self.date.isoformat(),
            starts_at=self.starts_at.isoformat(),
            ends_at=self.ends_at.isoformat(),
            teachers=list(self.teachers),
            groups=[asdict(group) for group in self.groups],
            links=list(self.links),
        )
        return result
