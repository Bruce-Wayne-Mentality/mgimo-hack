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


async def _seed(url: str) -> dict:
    from .accounts.seed import seed_demo
    from .db import Database

    from .student_requests.seed import seed_demo_requests, seed_request_types

    database = Database(url, pooled=False)
    try:
        created = await seed_demo(database)
        created["request_types"] = await seed_request_types(database)
        created["requests"] = await seed_demo_requests(database)
        return created
    finally:
        await database.dispose()


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

    seed = commands.add_parser("seed-demo", help="Создать вымышленные факультеты, группы и тестовые аккаунты")
    seed.add_argument("--database-url", help="По умолчанию переменная DATABASE_URL")

    serve = commands.add_parser("serve", help="Запустить API и личный кабинет")
    serve.add_argument("--demo", action="store_true", help="Синтетическое расписание и тестовые аккаунты для жюри")
    serve.add_argument("--database-url", help="По умолчанию DATABASE_URL; в --demo без него используется SQLite")
    serve.add_argument("--web-dist", type=Path, help="Собранный фронтенд (по умолчанию apps/web/dist, если есть)")
    serve.add_argument("--insecure-cookies", action="store_true", help="Кука без Secure — только для разработки по HTTP")
    serve.add_argument("--students", type=Path, default=Path("examples/students.json"))
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
            database_url = _database_url(args)
            if args.demo and not database_url:
                state_dir.mkdir(parents=True, exist_ok=True)
                database_url = f"sqlite:///{(state_dir / 'app.sqlite3').resolve().as_posix()}"
            tokens = {}
            if args.demo:
                fixture = Path("examples/lessons.json")
            else:
                fixture = args.fixture
                if args.tokens_file is None and not database_url:
                    raise ConfigurationError("Укажите DATABASE_URL (вход по логину) или --tokens-file, либо запустите --demo.")
                if args.tokens_file is not None:
                    tokens = json.loads(args.tokens_file.read_text(encoding="utf-8"))
                    if not isinstance(tokens, dict) or not tokens:
                        raise ConfigurationError("Файл токенов должен содержать непустой объект token → email.")
            service = _service(args.students, fixture, demo=args.demo)
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
                auth_settings = AuthSettings(
                    secret=_session_secret(state_dir, args.demo),
                    cookie_secure=not args.insecure_cookies,
                    demo=args.demo,
                )
            web_dist = args.web_dist or (WEB_DIST if (WEB_DIST / "index.html").is_file() else None)
            if web_dist is not None and auth is None:
                raise ConfigurationError("Личный кабинет требует входа по логину: задайте DATABASE_URL.")
            app = create_app(
                service, tokens, demo=args.demo, notification_store=store,
                push_sender=push, telegram_bot=bot, run_workers=True,
                refresh_interval=args.refresh_interval, auth=auth, auth_settings=auth_settings,
                demo_accounts=demo_accounts, web_dist=web_dist, request_service=request_service,
            )
            uvicorn.run(app, host=args.host, port=args.port)
        return 0
    except (ScheduleError, ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
