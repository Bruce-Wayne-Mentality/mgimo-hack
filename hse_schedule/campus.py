"""Campus services found in the benchmark of 30 universities (BENCHMARK_AND_IMPLEMENTATION.md):

- global search over services, disciplines, teachers, rooms, requests, announcements and rules
  (HSE App X, InNoHassle Search, Polimi App);
- «free rooms right now» from bookings and the timetable (Polimi, TU Delft Spacefinder, InNoHassle);
- teacher directory with consultation hours (MIT directory, ITMO консультации, HSE search);
- canteen menus (TUM, RWTH, EPFL, MIT, Michigan, Stanford);
- room finder with building, floor and directions (Imperial, UCL, Stanford, EPFL maps).

All data is fictional demo data; nothing is fetched from a real university.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from fastapi import Depends, FastAPI, Query
from sqlalchemy import select

from .accounts.models import StudyGroup, User
from .accounts.router import ApiError
from .accounts.service import CurrentSession
from .db import Database, utcnow

MOSCOW = ZoneInfo("Europe/Moscow")

# Pages of the cabinet (title, keywords, link, roles). The same words students type.
SERVICES = [
    ("Расписание", "пары занятия неделя аудитория", "/schedule", ("student",)),
    ("Календарь и подписка .ics", "календарь ical google apple дедлайны экспорт", "/calendar", ("student",)),
    ("Учёба: светофор и оценки", "оценки баллы светофор успеваемость средний балл стипендия сессия", "/study", ("student",)),
    ("Новая заявка", "справка заявление выписка военкомат пересдача академ перевод", "/requests/new", ("student",)),
    ("Мои заявки", "заявки справки статус документы pdf", "/requests", ("student",)),
    ("Красная кнопка", "жалоба несправедливость обращение проблема предложение благодарность", "/complaints/new", ("student",)),
    ("Студенческий билет", "студенческий qr пропуск вход охрана id", "/student-id", ("student",)),
    ("Ассистент", "вопрос помощь ии бот чат", "/assistant", ("student",)),
    ("Бронирование", "бронь коворкинг аудитория переговорная консультация приём", "/booking", ("student", "staff", "admin")),
    ("Свободные аудитории сейчас", "свободно сейчас аудитория пустая где позаниматься", "/campus?tab=free", ("student", "staff", "admin")),
    ("Корпуса и аудитории", "карта корпус этаж где аудитория как пройти навигация", "/campus", ("student", "staff", "admin")),
    ("Преподаватели", "преподаватель консультация часы приёма контакты кафедра", "/teachers", ("student", "staff", "admin")),
    ("Столовые", "столовая меню обед кафе еда буфет", "/canteen", ("student", "staff", "admin")),
    ("Жизненные ситуации", "академ перевод не сдал экзамен мастер", "/situations", ("student",)),
    ("Уведомления", "уведомления объявления push telegram", "/notifications", ("student",)),
    ("Профиль и безопасность", "профиль пароль сессии выйти", "/profile", ("student", "staff", "admin")),
    ("Очередь заявок", "очередь заявки sla просрочка", "/staff/requests", ("staff", "admin")),
    ("Журнал оценок", "журнал оценки баллы группа", "/staff/grades", ("staff", "admin")),
    ("Расписание групп", "перенос отмена замена аудитории", "/staff/schedule", ("staff", "admin")),
    ("Объявления", "объявление рассылка группе курсу", "/staff/announcements", ("staff", "admin")),
    ("Обращения", "красная кнопка жалобы обращения модерация", "/staff/complaints", ("staff", "admin")),
    ("О проекте", "о проекте лицензии безопасность концепт", "/about", ("student", "staff", "admin")),
]

BUILDINGS = {
    "А": {"title": "Корпус А", "address": "Учебная ул., 1 (вымышленный адрес)", "floors": 4,
          "note": "Главный вход, деканаты, лекционные аудитории, коворкинг «Атриум» на 1 этаже."},
    "Б": {"title": "Корпус Б", "address": "Учебная ул., 1, стр. 2", "floors": 3,
          "note": "Семинарские аудитории и компьютерные классы. Переход из корпуса А на 2 этаже."},
    "В": {"title": "Корпус В", "address": "Учебная ул., 3", "floors": 5,
          "note": "Математические кафедры, языковые аудитории, библиотека на 3 этаже."},
}

CANTEENS = [
    {"id": "main", "title": "Столовая корпуса А", "place": "Корпус А, цокольный этаж", "hours": "08:30–18:00", "busy": "12:30–13:30"},
    {"id": "cafe", "title": "Кафе «Перемена»", "place": "Корпус В, 1 этаж", "hours": "09:00–20:00", "busy": "11:00–12:00"},
]
DISHES = {
    "Супы": [("Борщ со сметаной", 95, False), ("Куриный суп с лапшой", 90, False), ("Крем-суп из тыквы", 85, True),
             ("Солянка", 110, False), ("Грибной суп", 90, True), ("Щи из свежей капусты", 80, True)],
    "Горячее": [("Котлета по-киевски", 165, False), ("Плов с курицей", 150, False), ("Паста с овощами", 135, True),
                ("Рыба на пару", 175, False), ("Гречка с грибами", 110, True), ("Бефстроганов", 180, False),
                ("Овощное рагу", 115, True)],
    "Гарниры": [("Картофельное пюре", 55, True), ("Рис с овощами", 55, True), ("Булгур", 60, True), ("Гречка", 45, True)],
    "Салаты": [("Винегрет", 60, True), ("Цезарь с курицей", 140, False), ("Овощной с маслом", 65, True), ("Оливье", 85, False)],
    "Выпечка и напитки": [("Сырник со сметаной", 70, True), ("Морс клюквенный", 45, True), ("Капучино", 120, True),
                          ("Пирожок с капустой", 40, True)],
}
FIRST_TIME = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]


def room_location(room: str | None) -> dict | None:
    """«Б-118» → building Б, floor 1. Fictional campus rules shared by all screens."""
    if not room:
        return None
    match = re.match(r"^\s*([АБВ])-(\d)(\d{1,2})\s*$", room)
    if not match:
        return None
    letter, floor = match.group(1), int(match.group(2))
    building = BUILDINGS[letter]
    if floor == 0:
        floor_text = "цокольный этаж"
    else:
        floor_text = f"{floor} этаж"
    wing = "левое крыло" if int(match.group(3)) < 50 else "правое крыло"
    route = {
        "А": "От главного входа — прямо к лифтам",
        "Б": "Через переход из корпуса А на 2 этаже или отдельный вход со двора",
        "В": "Отдельное здание через двор, вход с турникетами",
    }[letter]
    return {"room": room.strip(), "building": letter, "building_title": building["title"], "address": building["address"],
            "floor": floor, "floor_text": floor_text, "wing": wing,
            "directions": f"{route}, {floor_text}, {wing}."}


def consultation_hours(teacher: str) -> list[dict]:
    """Deterministic fictional office hours per teacher."""
    digest = int(hashlib.sha256(teacher.encode()).hexdigest(), 16)
    day = digest % 5
    start = [14, 15, 16][digest // 5 % 3]
    rooms = ["А-210", "Б-220", "В-212", "Б-118", "А-305"]
    second = (day + 2) % 5
    return [
        {"weekday": day, "weekday_label": FIRST_TIME[day], "time": f"{start:02d}:40–{start + 1:02d}:40", "room": rooms[digest % 5]},
        {"weekday": second, "weekday_label": FIRST_TIME[second], "time": "17:50–18:30", "room": "онлайн (ссылка в объявлении)"},
    ]


class CampusService:
    def __init__(self, database: Database, schedule=None, booking=None, clock=utcnow) -> None:
        self.database = database
        self.schedule = schedule
        self.booking = booking
        self.clock = clock

    # ---- free rooms right now ------------------------------------------------------

    async def free_now(self) -> dict:
        from .booking import Resource

        now = self.clock()
        local = now.astimezone(MOSCOW)
        today = local.date()
        items = []
        async with self.database.session() as db:
            resources = list((await db.scalars(select(Resource).where(
                Resource.is_bookable.is_(True), Resource.kind.in_(("classroom", "coworking"))))).all())
            for resource in resources:
                open_at = datetime.combine(today, time.fromisoformat(resource.opens), tzinfo=MOSCOW)
                close_at = datetime.combine(today, time.fromisoformat(resource.closes), tzinfo=MOSCOW)
                if not open_at <= local < close_at:
                    continue
                busy = sorted(await self.booking._busy(db, resource, today), key=lambda b: b[0]) if self.booking else []
                current = next((b for b in busy if b[0] <= now < b[1]), None)
                if current is not None:
                    continue
                upcoming = next((b for b in busy if b[0] > now), None)
                until = min(upcoming[0], close_at) if upcoming else close_at
                minutes = int((until - now).total_seconds() // 60)
                if minutes < 20:
                    continue
                items.append({
                    "id": str(resource.id), "title": resource.title, "kind": resource.kind,
                    "building": resource.building, "floor": resource.floor, "capacity": resource.capacity,
                    "free_until": until.isoformat(), "minutes": minutes,
                    "next": None if not upcoming else ("пара" if upcoming[2] == "lesson" else "бронь"),
                    "location": room_location(resource.room) if resource.room else None,
                })
        items.sort(key=lambda item: -item["minutes"])
        return {"at": now.isoformat(), "items": items}

    # ---- teachers -------------------------------------------------------------------

    async def teachers(self, user: User) -> list[dict]:
        from .academics.models import Discipline
        from .booking import Resource

        async with self.database.session() as db:
            query = select(Discipline, StudyGroup.code).join(StudyGroup, Discipline.group_id == StudyGroup.id)
            if user.role == "student" and user.student is not None:
                query = query.where(Discipline.group_id == user.student.group_id)
            rows = (await db.execute(query)).all()
            consult = {r.host.split(",")[0].split()[0]: str(r.id) for r in (await db.scalars(
                select(Resource).where(Resource.kind == "consultation"))).all() if r.host}
        teachers: dict[str, dict] = {}
        for discipline, group in rows:
            entry = teachers.setdefault(discipline.teacher_name, {
                "name": discipline.teacher_name, "disciplines": [], "groups": set(),
                "hours": consultation_hours(discipline.teacher_name),
                "email": f"{_translit(discipline.teacher_name.split()[0])}@demo-university.test",
            })
            if discipline.title not in [d["title"] for d in entry["disciplines"]]:
                entry["disciplines"].append({"id": str(discipline.id) if user.role == "student" else None, "title": discipline.title})
            entry["groups"].add(group)
        result = []
        for entry in teachers.values():
            surname = entry["name"].split()[0]
            result.append({**entry, "groups": sorted(entry["groups"]),
                           "booking_resource": consult.get(surname)})
        return sorted(result, key=lambda e: e["name"])

    # ---- canteen ----------------------------------------------------------------------

    def canteen(self, day: date) -> dict:
        menus = []
        for canteen in CANTEENS:
            seed = int(hashlib.sha256(f"{canteen['id']}|{day.isoformat()}".encode()).hexdigest(), 16)
            sections = []
            for index, (section, dishes) in enumerate(DISHES.items()):
                count = 2 if section != "Горячее" else 3
                start = (seed >> (index * 4)) % len(dishes)
                picked = [dishes[(start + i) % len(dishes)] for i in range(count)]
                sections.append({"title": section, "items": [
                    {"name": name, "price": price + (10 if canteen["id"] == "cafe" else 0), "vegetarian": veg}
                    for name, price, veg in picked]})
            lunch = sum(s["items"][0]["price"] for s in sections[:3])
            menus.append({**canteen, "sections": sections, "lunch_price": round(lunch * 0.85 / 10) * 10,
                          "open": day.weekday() < 6})
        return {"date": day.isoformat(), "weekday": FIRST_TIME[day.weekday()], "canteens": menus,
                "note": "Меню и цены вымышленные (демо)."}

    # ---- rooms ---------------------------------------------------------------------------

    def rooms(self) -> dict:
        from .academics.curriculum import DISCIPLINES

        seen: dict[str, dict] = {}
        for items in DISCIPLINES.values():
            for discipline in items:
                for _, _, _, room, _ in discipline["slots"]:
                    location = room_location(room)
                    if location and room not in seen:
                        seen[room] = location
        buildings = [{"letter": letter, **data, "rooms": sorted(
            (r for r in seen.values() if r["building"] == letter), key=lambda r: (r["floor"], r["room"]))}
            for letter, data in BUILDINGS.items()]
        return {"buildings": buildings}

    # ---- search -----------------------------------------------------------------------------

    async def search(self, user: User, q: str) -> dict:
        from .academics.models import Discipline
        from .announcements import Announcement
        from .assistant.knowledge import DOCUMENTS
        from .booking import Resource
        from .student_requests.models import RequestType, StudentRequest

        text = q.strip().lower().replace("ё", "е")
        terms = [t for t in re.split(r"\s+", text) if t]
        if not terms:
            return {"q": q, "groups": []}

        def hit(*fields: str) -> bool:
            haystack = " ".join(f or "" for f in fields).lower().replace("ё", "е")
            return all(term[:5] in haystack for term in terms)

        groups: list[dict] = []
        services = [{"title": title, "subtitle": "Раздел кабинета", "link": link}
                    for title, words, link, roles in SERVICES if user.role in roles and hit(title, words)]
        if services:
            groups.append({"key": "services", "title": "Разделы", "items": services[:8]})

        async with self.database.session() as db:
            query = select(Discipline)
            if user.role == "student" and user.student is not None:
                query = query.where(Discipline.group_id == user.student.group_id)
            disciplines = list((await db.scalars(query)).all())
            types = list((await db.scalars(select(RequestType).where(RequestType.is_active.is_(True)))).all())
            resources = list((await db.scalars(select(Resource))).all())
            own = []
            if user.role == "student" and user.student is not None:
                own = list((await db.scalars(select(StudentRequest).where(StudentRequest.student_id == user.student.id))).unique().all())
            announcements = []
            if user.role == "student":
                from .announcements import AnnouncementService

                announcements = await AnnouncementService(self.database).for_student(user)
            else:
                announcements = [{"title": a.title, "body": a.body} for a in (await db.scalars(
                    select(Announcement).where(Announcement.archived.is_(False)))).all()]

        items = [{"title": d.title, "subtitle": f"{d.teacher_name}", "link": f"/study/{d.id}" if user.role == "student" else "/staff/grades"}
                 for d in disciplines if hit(d.title, d.code)]
        if items:
            groups.append({"key": "disciplines", "title": "Дисциплины", "items": _unique(items)[:6]})
        teachers = _unique([{"title": d.teacher_name, "subtitle": d.title, "link": f"/teachers?q={d.teacher_name.split()[0]}"}
                            for d in disciplines if hit(d.teacher_name)], key="title")
        if teachers:
            groups.append({"key": "teachers", "title": "Преподаватели", "items": teachers[:6]})
        rooms = []
        for room in sorted({room for d in self.rooms()["buildings"] for room in [r["room"] for r in d["rooms"]]}):
            location = room_location(room)
            if hit(room, location["building_title"] if location else ""):
                rooms.append({"title": room, "subtitle": f"{location['building_title']}, {location['floor_text']}", "link": f"/campus?room={room}"})
        rooms += [{"title": r.title, "subtitle": f"{r.building}, {r.floor} этаж · бронирование", "link": "/booking"}
                  for r in resources if hit(r.title, r.code, r.building, " ".join(r.features or []))]
        if rooms:
            groups.append({"key": "rooms", "title": "Аудитории и помещения", "items": rooms[:8]})
        if user.role == "student":
            create = [{"title": t.title, "subtitle": "Подать заявку", "link": f"/requests/new?type={t.code}"}
                      for t in types if hit(t.title, t.description)]
            mine = [{"title": f"{r.number} · {r.type.title}", "subtitle": "Моя заявка", "link": f"/requests/{r.id}"}
                    for r in own if hit(r.number, r.type.title)]
            if create or mine:
                groups.append({"key": "requests", "title": "Заявки и справки", "items": (mine + create)[:8]})
        news = [{"title": a["title"], "subtitle": a["body"][:90], "link": "/notifications?tab=announcements"}
                for a in announcements if hit(a["title"], a["body"])]
        if news:
            groups.append({"key": "announcements", "title": "Объявления", "items": news[:5]})
        rules = [{"title": doc["title"], "subtitle": doc["text"][:100] + "…", "link": f"/assistant?q={doc['title']}"}
                 for doc in DOCUMENTS if hit(doc["title"], doc["keywords"])]
        if rules:
            groups.append({"key": "rules", "title": "Правила (ответит ассистент)", "items": rules[:5]})
        return {"q": q, "groups": groups}


def _unique(items: list[dict], key: str = "title") -> list[dict]:
    seen, out = set(), []
    for item in items:
        if item[key] not in seen:
            seen.add(item[key])
            out.append(item)
    return out


_TRANSLIT = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
                     ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t",
                      "u", "f", "kh", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _translit(word: str) -> str:
    return "".join(_TRANSLIT.get(c, c) for c in word.lower())


def register_campus_routes(app: FastAPI, service: CampusService) -> None:
    require_session = app.state.require_session

    @app.get("/api/search", tags=["campus"])
    async def search(q: str = Query(min_length=1, max_length=80), current: CurrentSession = Depends(require_session)) -> dict:
        return await service.search(current.user, q)

    @app.get("/api/campus/free-now", tags=["campus"])
    async def free_now(current: CurrentSession = Depends(require_session)) -> dict:
        return await service.free_now()

    @app.get("/api/campus/rooms", tags=["campus"])
    async def rooms(current: CurrentSession = Depends(require_session)) -> dict:
        return service.rooms()

    @app.get("/api/campus/room", tags=["campus"])
    async def room(code: str = Query(min_length=2, max_length=16), current: CurrentSession = Depends(require_session)) -> dict:
        location = room_location(code)
        if location is None:
            raise ApiError(404, "not_found", "Такой аудитории нет. Формат: буква корпуса и номер, например Б-118.")
        return location

    @app.get("/api/teachers", tags=["campus"])
    async def teachers(current: CurrentSession = Depends(require_session)) -> dict:
        return {"items": await service.teachers(current.user)}

    @app.get("/api/canteen", tags=["campus"])
    async def canteen(day: date | None = Query(default=None, alias="date"), current: CurrentSession = Depends(require_session)) -> dict:
        today = service.clock().astimezone(MOSCOW).date()
        day = day or today
        if not today - timedelta(days=1) <= day <= today + timedelta(days=7):
            raise ApiError(422, "validation_failed", "Меню — на неделю вперёд.")
        return service.canteen(day)
