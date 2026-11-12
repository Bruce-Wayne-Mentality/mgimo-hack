"""Source-independent objects consumed by the personal account website."""

from dataclasses import asdict, dataclass
from datetime import date, datetime


@dataclass(frozen=True, slots=True)
class Group:
    oid: str
    name: str


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
