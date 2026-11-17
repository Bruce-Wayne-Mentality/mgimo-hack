"""Command-line parsing, personal schedule lookup and local API startup."""

import argparse
import json
import math
import os
import sys
from dataclasses import asdict
from datetime import date
from pathlib import Path

from .client import HSEClient
from .errors import ConfigurationError, ScheduleError
from .parser import parse_lessons

WEB_DIST = Path("apps/web/dist")
DEMO_WEEK = Path("examples/demo-week.json")
DEMO_STUDENTS = Path("examples/demo-students.json")


def _database_url(args) -> str | None:
    from .db import database_url_from_env

    return args.database_url or database_url_from_env()


def _session_secret(state_dir: Path, demo: bool) -> bytes:
    value = os.environ.get("SESSION_SECRET", "").strip()
    if value:
        if len(value) < 32:
            raise ConfigurationError("SESSION_SECRET должен быть не короче 32 символов.")
        return value.encode("utf-8")
    if not demo:
        raise ConfigurationError("Задайте SESSION_SECRET (случайная строка от 32 символов).")
    # Demo convenience: a random secret kept next to the demo state.
    path = state_dir / "session-secret"
    if not path.exists():
        import secrets

        state_dir.mkdir(parents=True, exist_ok=True)
        path.write_text(secrets.token_urlsafe(48), encoding="utf-8")
        path.chmod(0o600)
    return path.read_text(encoding="utf-8").strip().encode("utf-8")


def _run(coroutine):
    import asyncio

    return asyncio.run(coroutine)


async def _seed_database(database) -> dict:
    from .academics.seed import seed_academics
    from .accounts.seed import seed_demo
    from .announcements import seed_announcements
    from .booking import seed_booking
    from .redbutton.seed import seed_redbutton
    from .student_requests.seed import seed_demo_requests, seed_request_types

    created = await seed_demo(database)
    created["request_types"] = await seed_request_types(database)
    created["academics"] = await seed_academics(database)
    created["requests"] = await seed_demo_requests(database)
    created["announcements"] = await seed_announcements(database)
    created["complaints"] = await seed_redbutton(database)
    created["resources"] = await seed_booking(database)
    if DEMO_WEEK.is_file() and DEMO_STUDENTS.is_file():
        from .schedule_changes import seed_schedule_changes

        created["schedule_changes"] = await seed_schedule_changes(database, _service(DEMO_STUDENTS, DEMO_WEEK, demo=True))
    return created


async def _seed(url: str) -> dict:
    from .db import Database

    database = Database(url, pooled=False)
    try:
        return await _seed_database(database)
    finally:
        await database.dispose()


def _modules(database, store, secret: bytes, schedule, request_service, *, demo: bool = False, overlay=None) -> tuple:
    """Route registrations of the feature modules sharing one database and notification store."""
    from datetime import datetime, timezone

    from .academics.router import register_academic_routes
    from .academics.service import AcademicService
    from .announcements import AnnouncementService, register_announcement_routes
    from .assistant.router import register_assistant_routes
    from .booking import BookingService, register_booking_routes
    from .calendar_feed import CalendarService, register_calendar_routes
    from .gigachat import GigaChat
    from .redbutton.crypto import KeyStore
    from .redbutton.router import register_redbutton_routes
    from .redbutton.service import RedButtonService
    from .admin import register_admin_routes
    from .documents.router import register_document_routes
    from .documents.service import DocumentService
    from .schedule_changes import Overlay, ScheduleChangeService, register_schedule_change_routes
    from .student_id import StudentIdService, register_student_id_routes

    def notify(email: str, drafts: list[dict]) -> None:
        store.publish_notifications(email, drafts, datetime.now(timezone.utc))

    base_url = os.environ.get("PUBLIC_BASE_URL") or None
    academics = AcademicService(database, notify=notify)
    documents = DocumentService(database, secret, base_url=base_url)
    student_id = StudentIdService(database, secret, base_url=base_url)
    announcements = AnnouncementService(database, notify=notify)
    booking = BookingService(database, schedule, notify=notify)
    calendar = CalendarService(database, schedule, extra_sources=(booking.calendar_events,))
    gigachat = GigaChat.from_env()
    redbutton = RedButtonService(database, keys=KeyStore(), gigachat=gigachat, notify=notify)
    overlay = overlay or Overlay()
    changes = ScheduleChangeService(database, schedule, overlay)

    async def reload_overlay() -> None:
        from sqlalchemy import select

        from .schedule_changes import LessonChange

        async with database.session() as db:
            overlay.replace_all(list((await db.scalars(select(LessonChange))).all()))

    return (
        lambda app: register_academic_routes(app, academics),
        lambda app: register_document_routes(app, documents),
        lambda app: register_student_id_routes(app, student_id),
        lambda app: register_announcement_routes(app, announcements),
        lambda app: register_calendar_routes(app, calendar),
        lambda app: register_redbutton_routes(app, redbutton),
        lambda app: register_booking_routes(app, booking),
        lambda app: register_assistant_routes(app, academics, request_service, schedule),
        lambda app: register_schedule_change_routes(app, changes),
        lambda app: register_admin_routes(app, database, store, demo=demo, reseed=_seed_database, on_reset=reload_overlay),
    )


def _dates(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="Начало, YYYY-MM-DD")
    parser.add_argument("--finish", type=date.fromisoformat, required=True, help="Конец включительно, YYYY-MM-DD")


def _output(payload: object, path: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(text, end="")
    else:
        path.write_text(text, encoding="utf-8")


def _service(students: Path, fixture: Path | None, *, demo: bool = False):
    from .directory import StudentDirectory
    from .service import FixtureSource, ScheduleService, WeeklyDemoSource

    source_type = WeeklyDemoSource if demo else FixtureSource
    source = source_type(fixture) if fixture else HSEClient()
    return ScheduleService(StudentDirectory.from_file(students), source)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Расписание ВШЭ и API личного кабинета учебного офиса")
    commands = parser.add_subparsers(dest="command", required=True)

    groups = commands.add_parser("groups", help="Группы со страницы программы ВШЭ")
    groups.add_argument("--url", required=True, help="https://www.hse.ru/ba/ami/timetable")
    groups.add_argument("--output", type=Path)

    fetch = commands.add_parser("fetch", help="Получить расписание из ВШЭ")
    subject = fetch.add_mutually_exclusive_group(required=True)
    subject.add_argument("--group", help="OID учебной группы")
    subject.add_argument("--student", help="OID студента из авторизованного справочника")
    _dates(fetch)
    fetch.add_argument("--output", type=Path)

    parse = commands.add_parser("parse", help="Разобрать сохранённый JSON ВШЭ без сети")
    parse.add_argument("--input", type=Path, required=True)
    parse.add_argument("--output", type=Path)

    schedule = commands.add_parser("schedule", help="Личные пары по email из локального справочника")
    schedule.add_argument("--students", type=Path, default=Path("examples/students.json"))
    schedule.add_argument("--email", required=True)
    schedule.add_argument("--fixture", type=Path, help="Локальная выгрузка; без параметра используется ВШЭ")
    schedule.add_argument("--output", type=Path)
    _dates(schedule)

    db_upgrade = commands.add_parser("db-upgrade", help="Применить миграции БД (DATABASE_URL)")
    db_upgrade.add_argument("--database-url", help="По умолчанию переменная DATABASE_URL")

    reset = commands.add_parser("reset-demo", help="Стереть и заново создать демо-данные (для ночного сброса)")
    reset.add_argument("--database-url", help="По умолчанию переменная DATABASE_URL")
    reset.add_argument("--state-dir", type=Path, default=Path(".local-state"), help="Каталог состояния сервера")

    seed = commands.add_parser("seed-demo", help="Создать вымышленные факультеты, группы и тестовые аккаунты")
    seed.add_argument("--database-url", help="По умолчанию переменная DATABASE_URL")

    probe = commands.add_parser("gigachat-probe", help="Пробный вызов эмбеддингов GigaChat: модель, размерность, время")
    probe.add_argument("--model", help="По умолчанию GIGACHAT_EMBED_MODEL или Embeddings")

    serve = commands.add_parser("serve", help="Запустить API и личный кабинет")
    serve.add_argument("--demo", action="store_true", help="Синтетическое расписание и тестовые аккаунты для жюри")
    serve.add_argument("--database-url", help="По умолчанию DATABASE_URL; в --demo без него используется SQLite")
    serve.add_argument("--web-dist", type=Path, help="Собранный фронтенд (по умолчанию apps/web/dist, если есть)")
    serve.add_argument("--insecure-cookies", action="store_true", help="Кука без Secure — только для разработки по HTTP")
    serve.add_argument("--students", type=Path, help="Справочник студентов (в --demo — examples/demo-students.json)")
    serve.add_argument("--fixture", type=Path)
    serve.add_argument("--tokens-file", type=Path, help="Закрытый JSON-объект token → email")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.add_argument("--state-dir", type=Path, default=Path(".local-state"), help="История уведомлений и VAPID-ключ")
    serve.add_argument("--push-contact", default="mailto:notifications@university.test", help="Контакт владельца Web Push (mailto: или https:)")
    serve.add_argument("--refresh-interval", type=float, default=60, help="Проверка изменений расписания, секунды")
    args = parser.parse_args(argv)

    try:
        if args.command == "groups":
            _output([asdict(group) for group in HSEClient().groups(args.url)], args.output)
        elif args.command == "fetch":
            lessons = HSEClient().schedule(
                start=args.start, finish=args.finish, student_oid=args.student, group_oid=args.group
            )
            _output([lesson.to_dict() for lesson in lessons], args.output)
        elif args.command == "parse":
            lessons = parse_lessons(json.loads(args.input.read_text(encoding="utf-8")))
            _output([lesson.to_dict() for lesson in lessons], args.output)
        elif args.command == "reset-demo":
            url = _database_url(args)
            if not url:
                raise ConfigurationError("Задайте DATABASE_URL или --database-url.")
            from .admin import reset_demo_data
            from .db import Database
            from .migrate import upgrade
            from .notification_store import NotificationStore

            upgrade(url)
            store = NotificationStore(args.state_dir / "demo" / "notifications.sqlite3")
            os.environ.setdefault("REDBUTTON_KEY_DIR", str((args.state_dir / "demo" / "keys").resolve()))

            async def run() -> dict:
                database = Database(url, pooled=False)
                try:
                    return await reset_demo_data(database, store, _seed_database, by="nightly")
                finally:
                    await database.dispose()

            created = _run(run())
            store.close()
            print(f"Демо-данные сброшены: {created}")
        elif args.command == "gigachat-probe":
            from .gigachat import GigaChat, GigaChatUnavailable, probe

            giga = GigaChat.from_env()
            if giga is not None and args.model:
                giga.embed_model = args.model
            try:
                result = _run(probe(giga))
            except GigaChatUnavailable as error:
                print(f"GigaChat недоступен: {error}")
                return 1
            if not result["configured"]:
                print("Ключ не задан (GIGACHAT_CREDENTIALS) — пробный вызов пропущен.")
            else:
                print(f"Модель: {result['model']}; размерность вектора: {result['dimension']}; "
                      f"векторов: {result['count']}; время ответа: {result['latency_ms']} мс")
        elif args.command in ("db-upgrade", "seed-demo"):
            url = _database_url(args)
            if not url:
                raise ConfigurationError("Задайте DATABASE_URL или --database-url.")
            if args.command == "db-upgrade":
                from .migrate import upgrade

                upgrade(url)
                print("Миграции применены.")
            else:
                created = _run(_seed(url))
                print(f"Демо-данные: создано пользователей {created['users']}, групп {created['groups']}.")
        elif args.command == "schedule":
            service = _service(args.students, args.fixture)
            lessons = service.get_schedule(args.email, args.start, args.finish)
            _output([lesson.to_dict() for lesson in lessons], args.output)
        else:
            from .api import create_app
            import uvicorn

            if args.demo and (args.fixture or args.tokens_file):
                raise ConfigurationError("Для --demo не задавайте --fixture и --tokens-file.")
            state_dir = args.state_dir / ("demo" if args.demo else "live")
            # Red-button keys live next to the server state, outside the database and its backups.
            os.environ.setdefault("REDBUTTON_KEY_DIR", str((state_dir / "keys").resolve()))
            database_url = _database_url(args)
            if args.demo and not database_url:
                state_dir.mkdir(parents=True, exist_ok=True)
                database_url = f"sqlite:///{(state_dir / 'app.sqlite3').resolve().as_posix()}"
            tokens = {}
            students = args.students
            if args.demo:
                fixture = DEMO_WEEK
                students = students or DEMO_STUDENTS
            else:
                fixture = args.fixture
                if args.tokens_file is None and not database_url:
                    raise ConfigurationError("Укажите DATABASE_URL (вход по логину) или --tokens-file, либо запустите --demo.")
                if args.tokens_file is not None:
                    tokens = json.loads(args.tokens_file.read_text(encoding="utf-8"))
                    if not isinstance(tokens, dict) or not tokens:
                        raise ConfigurationError("Файл токенов должен содержать непустой объект token → email.")
            service = _service(students or Path("examples/students.json"), fixture, demo=args.demo)
            from .notification_store import NotificationStore
            from .push import WebPushSender
            from .telegram import TelegramBot

            if not math.isfinite(args.refresh_interval) or args.refresh_interval <= 0:
                raise ConfigurationError("Интервал проверки должен быть положительным.")
            store = NotificationStore(state_dir / "notifications.sqlite3")
            push = WebPushSender(state_dir / "vapid-private.pem", args.push_contact)
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            bot = TelegramBot(bot_token, username=os.environ.get("TELEGRAM_BOT_USERNAME")) if bot_token else None
            auth = auth_settings = None
            request_service = None
            modules = ()
            demo_accounts = ()
            if database_url:
                from .accounts.router import AuthSettings
                from .accounts.seed import DEMO_ACCOUNTS
                from .accounts.service import AuthService
                from .db import Database

                if args.demo:
                    from .migrate import upgrade

                    upgrade(database_url)
                    _run(_seed(database_url))
                    demo_accounts = DEMO_ACCOUNTS
                from datetime import datetime, timezone

                from .student_requests.service import RequestService

                database = Database(database_url)
                auth = AuthService(database)
                request_service = RequestService(
                    database,
                    notify=lambda email, drafts: store.publish_notifications(email, drafts, datetime.now(timezone.utc)),
                )
                secret = _session_secret(state_dir, args.demo)
                from .schedule_changes import Overlay

                overlay = Overlay()
                overlay.load(database_url)
                service.overlay = overlay
                modules = _modules(database, store, secret, service, request_service, demo=args.demo, overlay=overlay)
                auth_settings = AuthSettings(
                    secret=secret,
                    cookie_secure=not args.insecure_cookies,
                    demo=args.demo,
                )
            if args.insecure_cookies and args.host not in ("127.0.0.1", "localhost", "::1"):
                # Without Secure the session cookie would travel over plain HTTP: only for local development.
                raise ConfigurationError("--insecure-cookies разрешён только при --host 127.0.0.1 или localhost.")
            web_dist = args.web_dist or (WEB_DIST if (WEB_DIST / "index.html").is_file() else None)
            if web_dist is not None and auth is None:
                raise ConfigurationError("Личный кабинет требует входа по логину: задайте DATABASE_URL.")
            app = create_app(
                service, tokens, demo=args.demo, notification_store=store,
                push_sender=push, telegram_bot=bot, run_workers=True,
                refresh_interval=args.refresh_interval, auth=auth, auth_settings=auth_settings,
                demo_accounts=demo_accounts, web_dist=web_dist, request_service=request_service,
                modules=modules,
            )
            uvicorn.run(app, host=args.host, port=args.port)
        return 0
    except (ScheduleError, ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
