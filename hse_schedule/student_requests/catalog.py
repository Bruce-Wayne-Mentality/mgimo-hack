"""Starting catalogue of request types (section 4.4) and server-side form validation.

The catalogue lives in the database and can grow without code changes; this
module only seeds it. SLA values are concept assumptions, not real norms.
"""

from __future__ import annotations

import re
from datetime import date

FIELD_KINDS = ("text", "textarea", "int", "select", "date")

REQUEST_TYPES: tuple[dict, ...] = (
    {
        "code": "CERT_STUDY", "title": "Справка с места учёбы", "sla_days": 0, "auto_issue": True, "sort": 10,
        "description": "Подтверждает, что вы учитесь. Подходит для работы, банка, соцзащиты.",
        "result": "Готова сразу после отправки",
        "fields": [
            {"name": "destination", "label": "Куда нужна справка", "kind": "text", "required": True, "max_length": 200,
             "hint": "Например: по месту требования, в банк, в соцзащиту"},
            {"name": "copies", "label": "Количество экземпляров", "kind": "int", "required": True, "min": 1, "max": 5},
        ],
    },
    {
        "code": "TRANSCRIPT", "title": "Академическая справка / выписка", "sla_days": 0, "auto_issue": True, "sort": 20,
        "description": "Выписка дисциплин и оценок из зачётной книжки.",
        "result": "Готова сразу после отправки",
        "fields": [
            {"name": "language", "label": "Язык", "kind": "select", "required": True,
             "options": [{"value": "ru", "label": "Русский"}, {"value": "en", "label": "English"}]},
        ],
    },
    {
        "code": "CERT_INTERN", "title": "Справка для стажировки или практики", "sla_days": 2, "sort": 30,
        "description": "Для работодателя или места практики, оформляет сотрудник деканата.",
        "result": "Оформляет сотрудник деканата",
        "fields": [
            {"name": "organization", "label": "Организация", "kind": "text", "required": True, "max_length": 200},
            {"name": "period_from", "label": "Начало", "kind": "date", "required": True},
            {"name": "period_to", "label": "Окончание", "kind": "date", "required": True},
        ],
    },
    {
        "code": "CERT_MIL", "title": "Справка для военкомата", "sla_days": 2, "sort": 40,
        "description": "Для отсрочки или постановки на учёт.",
        "result": "Оформляет сотрудник деканата",
        "fields": [
            {"name": "purpose", "label": "Цель", "kind": "select", "required": True,
             "options": [{"value": "deferment", "label": "Отсрочка"}, {"value": "registration", "label": "Учёт"}]},
            {"name": "office", "label": "Военкомат", "kind": "text", "required": True, "max_length": 200},
        ],
    },
    {
        "code": "RETAKE", "title": "Направление на пересдачу", "sla_days": 2, "sort": 50,
        "description": "Направление с датой пересдачи по выбранной дисциплине.",
        "result": "Направление с датой",
        "fields": [
            {"name": "discipline", "label": "Дисциплина", "kind": "text", "required": True, "max_length": 200},
            {"name": "reason", "label": "Причина", "kind": "textarea", "required": True, "max_length": 1000},
        ],
    },
    {
        "code": "TRANSFER", "title": "Перевод в другую группу или на направление", "sla_days": 5, "sort": 60,
        "description": "Решение принимает деканат после рассмотрения.",
        "result": "Решение деканата",
        "fields": [
            {"name": "target", "label": "Куда перевестись", "kind": "text", "required": True, "max_length": 200},
            {"name": "reason", "label": "Причина", "kind": "textarea", "required": True, "max_length": 1000},
        ],
    },
    {
        "code": "ACAD_LEAVE", "title": "Академический отпуск", "sla_days": 5, "sort": 70,
        "description": "Отпуск по медицинским, семейным или иным основаниям.",
        "result": "Решение и приказ",
        "fields": [
            {"name": "basis", "label": "Основание", "kind": "select", "required": True,
             "options": [{"value": "medical", "label": "Медицинское"}, {"value": "family", "label": "Семейные обстоятельства"},
                         {"value": "military", "label": "Призыв"}, {"value": "other", "label": "Другое"}]},
            {"name": "period_from", "label": "С какого числа", "kind": "date", "required": True},
            {"name": "months", "label": "Срок, месяцев", "kind": "int", "required": True, "min": 1, "max": 24},
            {"name": "comment", "label": "Комментарий", "kind": "textarea", "required": False, "max_length": 1000},
        ],
    },
    {
        "code": "AID", "title": "Материальная помощь", "sla_days": 7, "sort": 80,
        "description": "Единовременная выплата по заявлению.",
        "result": "Решение комиссии",
        "fields": [
            {"name": "basis", "label": "Основание", "kind": "textarea", "required": True, "max_length": 1000},
        ],
    },
)

_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class PayloadError(ValueError):
    def __init__(self, fields: dict[str, str]) -> None:
        super().__init__("invalid payload")
        self.fields = fields


def validate_payload(fields: list[dict], payload: object) -> dict:
    """Check a submitted form against the type's fields; returns the cleaned payload."""
    if not isinstance(payload, dict):
        raise PayloadError({"payload": "Форма заполнена некорректно."})
    known = {field["name"]: field for field in fields}
    errors: dict[str, str] = {}
    for name in payload:
        if name not in known:
            errors[name] = "Неизвестное поле."
    cleaned: dict = {}
    for name, field in known.items():
        value = payload.get(name)
        if isinstance(value, str):
            value = value.strip()
        if value in (None, ""):
            if field.get("required"):
                errors[name] = "Заполните поле."
            continue
        kind = field["kind"]
        if kind in ("text", "textarea"):
            if not isinstance(value, str):
                errors[name] = "Нужен текст."
            elif len(value) > field.get("max_length", 1000):
                errors[name] = f"Не больше {field.get('max_length', 1000)} символов."
            else:
                cleaned[name] = value
        elif kind == "int":
            if isinstance(value, str) and value.isdigit():
                value = int(value)
            if not isinstance(value, int) or isinstance(value, bool):
                errors[name] = "Нужно целое число."
            elif not field.get("min", value) <= value <= field.get("max", value):
                errors[name] = f"От {field.get('min')} до {field.get('max')}."
            else:
                cleaned[name] = value
        elif kind == "select":
            options = {option["value"] for option in field.get("options", ())}
            if value not in options:
                errors[name] = "Выберите вариант из списка."
            else:
                cleaned[name] = value
        elif kind == "date":
            try:
                if not isinstance(value, str) or not _DATE.match(value):
                    raise ValueError
                date.fromisoformat(value)
                cleaned[name] = value
            except ValueError:
                errors[name] = "Укажите дату."
    for start, finish in (("period_from", "period_to"),):
        if start in cleaned and finish in cleaned and cleaned[finish] < cleaned[start]:
            errors[finish] = "Окончание раньше начала."
    if errors:
        raise PayloadError(errors)
    return cleaned


def display_payload(fields: list[dict], payload: dict) -> list[dict]:
    """Human labels/values in catalogue order (select values become their labels)."""
    rows = []
    for field in fields:
        if field["name"] not in payload:
            continue
        value = payload[field["name"]]
        if field["kind"] == "select":
            value = next((option["label"] for option in field.get("options", ()) if option["value"] == value), value)
        elif field["kind"] == "date":
            year, month, day = str(value).split("-")
            value = f"{day}.{month}.{year}"
        rows.append({"name": field["name"], "label": field["label"], "value": str(value)})
    return rows
