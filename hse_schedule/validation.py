"""Shared input validation for the CLI, API and source adapters."""

from datetime import date


def validate_date_range(start: date, finish: date) -> None:
    if finish < start:
        raise ValueError("Конец периода не может быть раньше начала.")
    if (finish - start).days >= 31:
        raise ValueError("Запрашивайте не более 31 дня включительно.")


def normalize_oid(value: object) -> str:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        raise ValueError("Идентификатор должен быть положительным целым числом.")
    text = str(value).strip()
    if not text.isascii() or not text.isdecimal() or int(text) <= 0:
        raise ValueError("Идентификатор должен быть положительным целым числом.")
    return str(int(text))
