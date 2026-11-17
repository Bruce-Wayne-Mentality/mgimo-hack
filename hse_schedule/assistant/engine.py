"""K4: the deanery assistant.

Three kinds of questions (section 5):
- «как устроено» — answered from the rule documents (knowledge.py), with the source;
- «про меня» — answered from the student's own data via server functions;
- «сделай за меня» — a draft request the student confirms with a button.

The assistant never changes data itself. «Позвать сотрудника» creates a
QUESTION request with a short summary of the dialogue in the staff queue.

Without a GigaChat key the deterministic engine answers; with
GIGACHAT_AUTH_KEY set, GigaChat rephrases the grounded answer (facts always
come from the database and the rule documents, never from the model).
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from .knowledge import DOCUMENTS
from .textsearch import STOP, stem, tokens  # noqa: F401  (shared with the knowledge base)

MOSCOW = ZoneInfo("Europe/Moscow")
DISCLAIMER = "Это ИИ. Он может ошибаться; важное проверьте у деканата."

INJECTION = re.compile(
    r"(игнорир|забудь\s+(все|всё|инструкц)|ignore\s+(all|previous)|system\s*prompt|системн\w+\s+промпт|"
    r"ты\s+теперь|притворись|jailbreak|developer\s+mode|режим\s+разработчика)", re.IGNORECASE)
OTHERS = re.compile(r"(оценк\w*|балл\w*|заявк\w*|данные|расписани\w*)\s+(другого|других|чуж\w+|однокурсник\w*|бориса|анны|веры|студента\s+\w+)",
                    re.IGNORECASE)


class Index:
    """Tiny BM25 over the rule documents."""

    def __init__(self, documents: list[dict]) -> None:
        self.documents = documents
        self.bags = [Counter(tokens(f"{d['title']} {d['title']} {d['keywords']} {d['keywords']} {d['text']}")) for d in documents]
        self.lengths = [sum(bag.values()) for bag in self.bags]
        self.avg = sum(self.lengths) / len(self.lengths)
        df: Counter = Counter()
        for bag in self.bags:
            df.update(bag.keys())
        n = len(documents)
        self.idf = {term: math.log(1 + (n - count + 0.5) / (count + 0.5)) for term, count in df.items()}

    def search(self, query: str, limit: int = 3) -> list[tuple[float, dict]]:
        terms = tokens(query)
        scored = []
        for doc, bag, length in zip(self.documents, self.bags, self.lengths):
            score = 0.0
            for term in terms:
                tf = bag.get(term, 0)
                if tf:
                    score += self.idf[term] * tf * 2.2 / (tf + 1.2 * (0.25 + 0.75 * length / self.avg))
            if score > 0:
                scored.append((score, doc))
        scored.sort(key=lambda item: -item[0])
        return scored[:limit]


INDEX = Index(DOCUMENTS)


@dataclass
class Reply:
    text: str
    kind: str = "rule"
    sources: list[dict] = field(default_factory=list)
    actions: list[dict] = field(default_factory=list)
    facts: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"text": self.text, "kind": self.kind, "sources": self.sources, "actions": self.actions, "facts": self.facts}


@dataclass
class StudentContext:
    """Facts the server already checked belong to the asking student."""

    first_name: str
    overview: dict | None
    lessons: list[dict]
    requests: list[dict]
    today: date


def _has(text: str, *patterns: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def _find_discipline(text: str, overview: dict | None) -> dict | None:
    if not overview:
        return None
    words = set(tokens(text))
    best, best_score = None, 0
    for item in overview["disciplines"]:
        title_words = set(tokens(item["title"]))
        score = len(words & title_words)
        if score > best_score:
            best, best_score = item, score
    return best


def _time(value: str) -> str:
    return datetime.fromisoformat(value).astimezone(MOSCOW).strftime("%H:%M")


def _day(value: date, today: date) -> str:
    if value == today:
        return "сегодня"
    if value == today + timedelta(days=1):
        return "завтра"
    months = ["января", "февраля", "марта", "апреля", "мая", "июня", "июля", "августа", "сентября", "октября", "ноября", "декабря"]
    return f"{value.day} {months[value.month - 1]}"


def answer(message: str, ctx: StudentContext, about: str | None = None, intent: str | None = None) -> Reply:
    text = message.strip().lower().replace("ё", "е")
    if about:
        text = f"{text} {about.lower()}"

    if INJECTION.search(text):
        return Reply("Я работаю только в рамках правил кабинета и не меняю свои инструкции. "
                     "Могу рассказать о правилах вуза или о ваших оценках, заявках и расписании.", kind="guard")
    if OTHERS.search(text):
        return Reply("Я показываю только ваши собственные данные — так устроена защита кабинета. "
                     "Данные других студентов недоступны ни мне, ни вам.", kind="guard")

    if intent == "consultation" or _has(text, r"консультац"):
        discipline = _find_discipline(text, ctx.overview)
        if discipline:
            return Reply(
                f"По дисциплине «{discipline['title']}» консультации ведёт {discipline['teacher']}. "
                f"Ближайшая — в день следующей пары после занятия (демо-правило). "
                f"Сейчас у вас {discipline['risk']['points']} баллов, статус «{discipline['risk']['label']}». "
                "Если нужно отдельное время, я передам вопрос в деканат — сотрудник согласует слот с преподавателем.",
                kind="me",
                actions=[{"kind": "handoff", "label": "Попросить деканат записать на консультацию",
                          "summary": f"Прошу записать на консультацию по дисциплине «{discipline['title']}»."},
                         {"kind": "link", "label": "Открыть дисциплину", "link": f"/study/{discipline['id']}"}],
            )

    if intent == "attendance" or _has(text, r"пропус", r"больнич", r"уважительн", r"болел"):
        doc = next(d for d in DOCUMENTS if d["id"] == "attendance")
        discipline = _find_discipline(text, ctx.overview)
        extra = ""
        if discipline and discipline["risk"].get("attendance") is not None:
            extra = f" По «{discipline['title']}» сейчас посещаемость {round(discipline['risk']['attendance'] * 100)}%."
        return Reply(doc["text"] + extra, kind="rule", sources=[{"id": doc["id"], "title": doc["title"]}],
                     actions=[{"kind": "handoff", "label": "Отправить объяснение в деканат",
                               "summary": "Пропуски по уважительной причине" + (f" по дисциплине «{discipline['title']}»" if discipline else "") + ". Документ приложу по запросу."}])

    # ---- «сделай за меня»: drafts ------------------------------------------------
    if _has(text, r"справк\w* .*(учеб|банк|работ|соцзащит|требован)", r"(нужна|дайте|получить|оформ\w+) справк", r"справк\w* с места"):
        if _has(text, r"военкомат", r"отсрочк"):
            return _draft("CERT_MIL", "Справка для военкомата", {"purpose": "deferment"},
                          "Подготовил черновик заявки на справку для военкомата. Укажите адрес военкомата и проверьте данные.")
        if _has(text, r"практик", r"стажировк"):
            return _draft("CERT_INTERN", "Справка для стажировки", {},
                          "Подготовил черновик справки для стажировки: впишите организацию и даты.")
        destination = "По месту требования"
        for pattern, value in ((r"банк", "В банк"), (r"соцзащит", "В органы соцзащиты"), (r"работ", "По месту работы"), (r"виз|посольств", "В посольство (для визы)")):
            if re.search(pattern, text):
                destination = value
        return _draft("CERT_STUDY", "Справка с места учёбы", {"destination": destination, "copies": 1},
                      f"Подготовил заявку на справку с места учёбы ({destination.lower()}). "
                      "Она выдаётся автоматически — PDF с QR-кодом будет готов сразу после подтверждения.")
    if _has(text, r"военкомат", r"отсрочк", r"приписн"):
        return _draft("CERT_MIL", "Справка для военкомата", {"purpose": "deferment"},
                      "Подготовил черновик заявки на справку для военкомата. Укажите полный адрес военкомата.")
    if _has(text, r"выписк", r"транскрипт", r"академическ\w* справк"):
        language = "en" if _has(text, r"англ", r"english") else "ru"
        return _draft("TRANSCRIPT", "Академическая справка", {"language": language},
                      "Подготовил заявку на выписку оценок. Она тоже выдаётся автоматически.")
    if _has(text, r"пересда", r"не сдал", r"завалил", r"провалил"):
        discipline = _find_discipline(text, ctx.overview)
        payload = {"discipline": discipline["title"]} if discipline else {}
        return _draft("RETAKE", "Направление на пересдачу", payload,
                      "Подготовил черновик направления на пересдачу" + (f" по «{discipline['title']}»" if discipline else "")
                      + ". Допишите причину. Если не уверены в последствиях, откройте мастер «Не сдал экзамен».",
                      extra=[{"kind": "link", "label": "Мастер «Не сдал экзамен»", "link": "/situations/failed-exam"}])
    if _has(text, r"академ\b", r"академическ\w* отпуск", r"взять академ"):
        return _rule("acad-leave", extra=[{"kind": "link", "label": "Открыть мастер «Хочу взять академ»", "link": "/situations/academic-leave"}])
    if _has(text, r"перевест", r"перевод"):
        return _rule("transfer", extra=[{"kind": "link", "label": "Открыть мастер «Хочу перевестись»", "link": "/situations/transfer"}])
    if _has(text, r"материальн", r"матпомощ"):
        return _draft("AID", "Материальная помощь", {}, "Подготовил черновик заявления на материальную помощь — опишите основание.")

    if _has(text, r"оспор", r"апелляц", r"несправедлив", r"занизил", r"не согласен с оценк", r"несогласен"):
        return _rule("appeal", extra=[{"kind": "link", "label": "Красная кнопка", "link": "/complaints/new"}])
    if _has(text, r"стипенди"):
        return _rule("scholarship")

    # ---- «про меня» -----------------------------------------------------------
    if _has(text, r"заявк", r"где мо\w+ справк", r"статус"):
        open_items = [r for r in ctx.requests if r["status"] in ("submitted", "in_review", "needs_info")]
        if not ctx.requests:
            return Reply("У вас пока нет заявок. Справку с места учёбы можно получить за минуту.", kind="me",
                         actions=[{"kind": "link", "label": "Новая заявка", "link": "/requests/new"}])
        lines = []
        for r in (open_items or ctx.requests[:3]):
            note = " — нужен ваш ответ" if r["status"] == "needs_info" else ""
            lines.append(f"• {r['type']['title']} ({r['number']}): {r['status_label'].lower()}{note}")
        head = f"Активных заявок: {len(open_items)}." if open_items else "Активных заявок нет, последние:"
        actions = [{"kind": "link", "label": f"Открыть {r['number']}", "link": f"/requests/{r['id']}"} for r in open_items[:2]]
        return Reply(head + "\n" + "\n".join(lines), kind="me", actions=actions or [{"kind": "link", "label": "Все заявки", "link": "/requests"}])

    if _has(text, r"пар[аыу]?\b", r"расписан", r"занят", r"аудитор", r"лекци", r"семинар", r"завтра", r"сегодня"):
        target = ctx.today + timedelta(days=1) if "завтра" in text else ctx.today
        day_lessons = [l for l in ctx.lessons if datetime.fromisoformat(l["starts_at"]).astimezone(MOSCOW).date() == target]
        if "следующ" in text or "ближайш" in text:
            now = datetime.now(MOSCOW)
            upcoming = [l for l in ctx.lessons if datetime.fromisoformat(l["ends_at"]) > now]
            if upcoming:
                l = upcoming[0]
                day = _day(datetime.fromisoformat(l["starts_at"]).astimezone(MOSCOW).date(), ctx.today)
                return Reply(f"Следующая пара — {l['title']} ({(l['kind'] or '').lower()}), {day} в {_time(l['starts_at'])}, "
                             f"{l['room'] or 'аудитория уточняется'}.", kind="me",
                             actions=[{"kind": "link", "label": "Расписание", "link": "/schedule"}])
        if not day_lessons:
            return Reply(f"{_day(target, ctx.today).capitalize()} пар нет.", kind="me",
                         actions=[{"kind": "link", "label": "Неделя целиком", "link": "/schedule"}])
        lines = [f"• {_time(l['starts_at'])}–{_time(l['ends_at'])} {l['title']} — {l['room'] or '—'}" for l in day_lessons]
        count = len(day_lessons)
        word = "пара" if count == 1 else "пары" if count < 5 else "пар"
        return Reply(f"{_day(target, ctx.today).capitalize()} {count} {word}:\n" + "\n".join(lines), kind="me",
                     actions=[{"kind": "link", "label": "Расписание", "link": "/schedule"}])

    if _has(text, r"дедлайн", r"что сдать", r"сдавать", r"контрольн", r"домашн"):
        if not ctx.overview:
            return Reply("Данных об успеваемости пока нет.", kind="me")
        upcoming = sorted(
            (d for d in ctx.overview["disciplines"] if d["next_checkpoint"] and d["next_checkpoint"]["days_left"] <= 14),
            key=lambda d: d["next_checkpoint"]["days_left"],
        )
        if not upcoming:
            return Reply("В ближайшие две недели дедлайнов нет.", kind="me")
        lines = [f"• {_day(date.fromisoformat(d['next_checkpoint']['due_on']), ctx.today)}: {d['next_checkpoint']['title']} — "
                 f"{d['title']} ({d['next_checkpoint']['weight']} баллов)" for d in upcoming[:5]]
        return Reply("Ближайшие дедлайны:\n" + "\n".join(lines), kind="me",
                     actions=[{"kind": "link", "label": "Календарь", "link": "/calendar"}])

    discipline = _find_discipline(text, ctx.overview) if ctx.overview else None
    if discipline and (_has(text, r"сколько", r"нужно", r"набрать", r"допуск", r"балл", r"успе", r"как.*дела", r"что делать") or about):
        risk = discipline["risk"]
        parts = [f"«{discipline['title']}»: {risk['label'].lower()}, {risk['points']} баллов из 100."]
        if risk["reasons"]:
            parts.append("Причина: " + risk["reasons"][0]["text"].lower() + ".")
        if discipline["next_checkpoint"]:
            nc = discipline["next_checkpoint"]
            parts.append(f"Следующая работа — «{nc['title']}» ({nc['weight']} баллов), {_day(date.fromisoformat(nc['due_on']), ctx.today)}.")
        missing = max(0, discipline["threshold"] - risk["points"])
        parts.append(f"До допуска ({discipline['threshold']} баллов) осталось {missing:g}." if missing else "Допуск по баллам уже набран.")
        return Reply(" ".join(parts), kind="me",
                     actions=[{"kind": "link", "label": "Открыть дисциплину и «Что если»", "link": f"/study/{discipline['id']}"}]
                     + [a for a in discipline["actions"] if a["kind"] == "retake"][:1])

    if _has(text, r"как.*(у меня )?дела", r"успеваемост", r"оценк", r"балл", r"светофор", r"риск", r"долг", r"сесси", r"средн"):
        if not ctx.overview or not ctx.overview["disciplines"]:
            return Reply("Оценок пока нет. Я напишу, когда появятся первые баллы.", kind="me")
        o = ctx.overview
        risky = [d for d in o["disciplines"] if d["risk"]["level"] in ("red", "yellow")]
        lines = [o["summary"]["headline"] + "."]
        for d in risky[:3]:
            reason = d["risk"]["reasons"][0]["text"].lower() if d["risk"]["reasons"] else ""
            lines.append(f"• {d['risk']['label']}: {d['title']} — {reason}.")
        if not risky:
            lines.append("Рисков нет — так держать.")
        if o.get("gpa"):
            lines.append(f"Средний балл по закрытым семестрам: {o['gpa']:.2f}.")
        actions = [{"kind": "link", "label": f"Что делать: {d['title']}", "link": f"/study/{d['id']}"} for d in risky[:2]]
        return Reply("\n".join(lines), kind="me", actions=actions or [{"kind": "link", "label": "Успеваемость", "link": "/study"}])

    if _has(text, r"^(привет|здравств|добр\w+ (день|утро|вечер)|хай|hello)"):
        return Reply(f"Здравствуйте, {ctx.first_name}! Я помогу с правилами вуза, вашими оценками, заявками и расписанием, "
                     "а ещё могу подготовить заявку — вы только подтвердите.", kind="hello")

    found = INDEX.search(text)
    if found and found[0][0] >= 1.2:
        return _rule(found[0][1]["id"], related=[doc for _, doc in found[1:2]])

    return Reply("Не уверен, что правильно понял вопрос, а гадать не буду. Могу передать его сотруднику деканата "
                 "вместе с кратким содержанием нашего диалога — вы увидите ответ в «Заявках».",
                 kind="fallback", actions=[{"kind": "handoff", "label": "Позвать сотрудника", "summary": message.strip()[:500]}])


def _rule(doc_id: str, extra: list[dict] | None = None, related: list[dict] | None = None) -> Reply:
    doc = next(d for d in DOCUMENTS if d["id"] == doc_id)
    actions = list(extra or [])
    if doc["link"] and not any(a.get("link") == doc["link"] for a in actions):
        actions.append({"kind": "link", "label": "Перейти", "link": doc["link"]})
    sources = [{"id": doc["id"], "title": doc["title"]}] + [{"id": d["id"], "title": d["title"]} for d in related or []]
    return Reply(doc["text"], kind="rule", sources=sources, actions=actions)


def _draft(code: str, title: str, payload: dict, text: str, extra: list[dict] | None = None) -> Reply:
    return Reply(text, kind="draft", actions=[{"kind": "draft", "label": f"Проверить и отправить: {title}",
                                               "type": code, "payload": payload}] + (extra or []))


SUGGESTIONS = [
    "Как у меня дела?",
    "Какие пары завтра?",
    "Нужна справка в банк",
    "Ближайшие дедлайны",
    "Что будет, если не сдам экзамен?",
    "Где моя заявка?",
]
