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

DEMO_TOKENS = {
    "demo-alice-token": "alice@demo-university.test",
    "demo-bob-token": "bob@demo-university.test",
}


def _dates(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="Начало, YYYY-MM-DD")
    parser.add_argument("--finish", type=date.fromisoformat, required=True, help="Конец включительно, YYYY-MM-DD")


def _output(payload: object, path: Path | None) -> None:
    text = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if path is None:
        print(text, end="")
    else:
        path.write_text(text, encoding="utf-8")


def _service(students: Path, fixture: Path | None):
    from .directory import StudentDirectory
    from .service import FixtureSource, ScheduleService

    source = FixtureSource(fixture) if fixture else HSEClient()
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

    serve = commands.add_parser("serve", help="Запустить API для личного кабинета")
    serve.add_argument("--demo", action="store_true", help="Синтетическое расписание и два тестовых аккаунта")
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
        elif args.command == "schedule":
            service = _service(args.students, args.fixture)
            lessons = service.get_schedule(args.email, args.start, args.finish)
            _output([lesson.to_dict() for lesson in lessons], args.output)
        else:
            from .api import create_app
            import uvicorn

            if args.demo and (args.fixture or args.tokens_file):
                raise ConfigurationError("Для --demo не задавайте --fixture и --tokens-file.")
            if args.demo:
                fixture = Path("examples/lessons.json")
                tokens = DEMO_TOKENS
            else:
                fixture = args.fixture
                if args.tokens_file is None:
                    raise ConfigurationError("Укажите --tokens-file или запустите --demo.")
                tokens = json.loads(args.tokens_file.read_text(encoding="utf-8"))
                if not isinstance(tokens, dict) or not tokens:
                    raise ConfigurationError("Файл токенов должен содержать непустой объект token → email.")
            service = _service(args.students, fixture)
            from .notification_store import NotificationStore
            from .push import WebPushSender
            from .telegram import TelegramBot

            if not math.isfinite(args.refresh_interval) or args.refresh_interval <= 0:
                raise ConfigurationError("Интервал проверки должен быть положительным.")
            state_dir = args.state_dir / ("demo" if args.demo else "live")
            store = NotificationStore(state_dir / "notifications.sqlite3")
            push = WebPushSender(state_dir / "vapid-private.pem", args.push_contact)
            bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
            bot = TelegramBot(bot_token, username=os.environ.get("TELEGRAM_BOT_USERNAME")) if bot_token else None
            app = create_app(
                service, tokens, demo=args.demo, notification_store=store,
                push_sender=push, telegram_bot=bot, run_workers=True,
                refresh_interval=args.refresh_interval,
            )
            uvicorn.run(app, host=args.host, port=args.port)
        return 0
    except (ScheduleError, ValueError, OSError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
