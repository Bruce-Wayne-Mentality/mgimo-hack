"""K1 «Как у меня дела»: the traffic light per discipline (section 5).

    P    = Σ_{graded} w_i · e_i / m_i      points earned
    W    = Σ_{due ≤ today} w_i              weight whose deadline has passed
                                           (work still being checked within
                                           the grace period is left out)
    pace = P / W                           share of what could have been earned
    R    = P + (100 − W)                   the best total still reachable

Rules on mock data, no ML. Thresholds are concept assumptions kept in
RiskConfig so they can be tuned without touching the code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta


@dataclass(frozen=True)
class RiskConfig:
    red_pace: float = 0.5
    yellow_pace: float = 0.7
    red_attendance: float = 0.60
    yellow_attendance: float = 0.75
    # A checkpoint counts as missed when it has no score this many days after its deadline.
    grace_days: int = 3


DEFAULT = RiskConfig()

LEVEL_ORDER = {"red": 0, "yellow": 1, "green": 2, "grey": 3}
LEVEL_LABELS = {"red": "Вне графика", "yellow": "Под риском", "green": "В графике", "grey": "Нет данных"}

REASON_TEXT = {
    "CANNOT_REACH_ADMISSION": "Даже с максимумом за оставшиеся работы не хватит баллов до допуска",
    "MISSED_CRITICAL": "Пропущена обязательная контрольная точка",
    "LOW_PACE": "Набрано меньше, чем можно было к сегодняшнему дню",
    "LOW_ATTENDANCE": "Низкая посещаемость",
    "MISSED_MINOR": "Не сдана контрольная точка",
}

# What to do for each reason (section 5, K1 «Действия по коду причины»).
REASON_ACTION = {
    "CANNOT_REACH_ADMISSION": {"kind": "consultation", "label": "Записаться на консультацию"},
    "LOW_PACE": {"kind": "consultation", "label": "Записаться на консультацию"},
    "MISSED_CRITICAL": {"kind": "retake", "label": "Подать заявку на пересдачу"},
    "MISSED_MINOR": {"kind": "retake", "label": "Подать заявку на пересдачу"},
    "LOW_ATTENDANCE": {"kind": "excuse", "label": "Сообщить об уважительной причине"},
}


@dataclass(frozen=True)
class CheckpointInput:
    weight: float
    max_score: float
    due_on: date | None
    score: float | None
    critical: bool = False
    title: str = ""


@dataclass(frozen=True)
class RiskResult:
    level: str
    p: float
    w: float
    pace: float | None
    r: float
    reasons: tuple[str, ...] = field(default_factory=tuple)
    missed: tuple[str, ...] = field(default_factory=tuple)
    attendance: float | None = None

    @property
    def label(self) -> str:
        return LEVEL_LABELS[self.level]

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "label": self.label,
            "points": round(self.p, 1),
            "due_weight": round(self.w, 1),
            "pace": None if self.pace is None else round(self.pace, 3),
            "reachable": round(self.r, 1),
            "reasons": [{"code": code, "text": REASON_TEXT[code]} for code in self.reasons],
            "missed": list(self.missed),
            "attendance": None if self.attendance is None else round(self.attendance, 3),
        }


def compute(
    checkpoints: list[CheckpointInput],
    *,
    today: date,
    threshold: float = 40,
    attended: int = 0,
    total_lessons: int = 0,
    config: RiskConfig = DEFAULT,
) -> RiskResult:
    p = 0.0
    w = 0.0
    missed_critical: list[str] = []
    missed_minor: list[str] = []
    for item in checkpoints:
        if item.score is not None:
            if item.score > item.max_score or item.score < 0:
                raise ValueError("score outside 0..max_score")
            p += item.weight * item.score / item.max_score
        if item.due_on is not None and item.due_on <= today:
            overdue = item.due_on + timedelta(days=config.grace_days) < today
            # Work still being checked (inside the grace period) does not lower the pace.
            if item.score is not None or overdue:
                w += item.weight
            if item.score is None and overdue:
                (missed_critical if item.critical else missed_minor).append(item.title)
    pace = p / w if w > 0 else None
    r = p + (100 - w)
    attendance = attended / total_lessons if total_lessons > 0 else None

    if w == 0:
        return RiskResult("grey", p, w, None, r, (), (), attendance)

    red: list[str] = []
    yellow: list[str] = []
    if r < threshold:
        red.append("CANNOT_REACH_ADMISSION")
    if missed_critical:
        red.append("MISSED_CRITICAL")
    if pace is not None and pace < config.red_pace:
        red.append("LOW_PACE")
    elif pace is not None and pace < config.yellow_pace:
        yellow.append("LOW_PACE")
    if attendance is not None and attendance < config.red_attendance:
        red.append("LOW_ATTENDANCE")
    elif attendance is not None and attendance < config.yellow_attendance:
        yellow.append("LOW_ATTENDANCE")
    if missed_minor:
        yellow.append("MISSED_MINOR")

    missed = tuple(missed_critical + missed_minor)
    if red:
        return RiskResult("red", p, w, pace, r, tuple(red + yellow), missed, attendance)
    if yellow:
        return RiskResult("yellow", p, w, pace, r, tuple(yellow), missed, attendance)
    return RiskResult("green", p, w, pace, r, (), missed, attendance)


def expected_by_today(checkpoints: list[CheckpointInput], today: date) -> float:
    """The «должно быть к сегодня» marker on the score bar: W in points."""
    return sum(item.weight for item in checkpoints if item.due_on is not None and item.due_on <= today)


def needed_for(target: float, result: RiskResult, remaining_weight: float) -> float | None:
    """Share of the remaining points needed to reach ``target`` total (None if impossible)."""
    missing = target - result.p
    if missing <= 0:
        return 0.0
    if remaining_weight <= 0 or missing > remaining_weight:
        return None
    return missing / remaining_weight


RULES_TEXT = [
    "Каждая контрольная точка имеет вес; все веса дисциплины в сумме дают 100 баллов.",
    "Темп — это доля баллов, которую вы набрали из тех, что уже можно было набрать к сегодняшнему дню.",
    "«В графике» — темп от 70%, посещаемость от 75% и нет пропущенных работ.",
    "«Под риском» — темп 50–70%, посещаемость 60–75% или не сдана необязательная работа.",
    "«Вне графика» — темп ниже 50%, посещаемость ниже 60%, пропущена обязательная работа "
    "или допуск уже недостижим даже с максимумом за оставшиеся работы.",
    "«Нет данных» — ни один срок по дисциплине ещё не наступил.",
    "Работа считается пропущенной, если через 3 дня после срока по ней нет балла. "
    "Пока работа на проверке, она не снижает темп.",
    "Это статус для помощи, а не рейтинг: мы не сравниваем вас с другими студентами. "
    "Пороги — допущения концепта, в реальном вузе их настраивает деканат.",
]
