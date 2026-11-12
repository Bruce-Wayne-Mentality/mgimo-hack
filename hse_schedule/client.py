"""HTTP adapter for the public timetable JSON used by hse.ru itself."""

import ssl
from datetime import date
from urllib.parse import urlsplit

import httpx

from .errors import InvalidPayload, SourceUnavailable
from .models import Group, Lesson
from .parser import parse_groups, parse_lessons
from .validation import normalize_oid, validate_date_range


class HSEClient:
    """Use the public portal, rather than the intranet-only ruz.hse.ru host.

    Student OIDs must come from an authorized roster. The public portal does
    not provide a supported email-to-student lookup. Individual lookup still
    depends on the upstream access policy.
    """

    def __init__(
        self,
        *,
        timeout: float = 20.0,
        transport: httpx.BaseTransport | None = None,
        base_url: str = "https://www.hse.ru/api/timetable",
        timezone: str = "Europe/Moscow",
    ) -> None:
        if timeout <= 0:
            raise ValueError("Таймаут должен быть положительным.")
        self.timeout = timeout
        self.transport = transport
        self.base_url = base_url.rstrip("/")
        self.timezone = timezone

    def _get(self, url: str, params: dict | None = None) -> httpx.Response:
        try:
            # The default SSL context preserves the environment's trusted CA.
            with httpx.Client(
                timeout=self.timeout,
                follow_redirects=False,
                verify=ssl.create_default_context(),
                transport=self.transport,
                headers={"User-Agent": "mgimo-hack-schedule/0.1", "Accept": "application/json, text/html"},
            ) as client:
                response = client.get(url, params=params)
            if response.is_redirect:
                raise SourceUnavailable(
                    "Источник перенаправил запрос. Проверьте доступ к расписанию; "
                    "для ruz.hse.ru требуется внутренняя сеть ВШЭ."
                )
            response.raise_for_status()
            return response
        except httpx.HTTPError as exc:
            raise SourceUnavailable("Не удалось загрузить расписание из ВШЭ.") from exc

    def schedule(
        self,
        *,
        start: date,
        finish: date,
        student_oid: str | None = None,
        group_oid: str | None = None,
    ) -> tuple[Lesson, ...]:
        validate_date_range(start, finish)
        if (student_oid is None) == (group_oid is None):
            raise ValueError("Укажите ровно один идентификатор: student_oid или group_oid.")
        params = {
            "fromdate": start.strftime("%Y.%m.%d"),
            "todate": finish.strftime("%Y.%m.%d"),
            "receiverType": 0 if student_oid is not None else 3,
            "studentoid" if student_oid is not None else "groupoid": normalize_oid(
                student_oid if student_oid is not None else group_oid
            ),
        }
        response = self._get(self.base_url + "/lessons", params)
        if "html" in response.headers.get("content-type", "").lower() or response.text.lstrip().startswith("<"):
            raise SourceUnavailable("Вместо расписания получена HTML-страница. Проверьте доступ к источнику.")
        try:
            payload = response.json()
        except ValueError as exc:
            raise InvalidPayload("Источник вернул некорректный JSON.") from exc
        lessons = parse_lessons(payload, timezone=self.timezone)
        # Enforce the requested interval even if the source returns extra days.
        return tuple(lesson for lesson in lessons if start <= lesson.date <= finish)

    def groups(self, program_url: str) -> tuple[Group, ...]:
        url = urlsplit(program_url)
        if (
            url.scheme != "https"
            or not url.hostname
            or not (url.hostname == "hse.ru" or url.hostname.endswith(".hse.ru"))
            or url.username is not None
            or url.password is not None
            or url.port not in (None, 443)
        ):
            raise ValueError("Нужна HTTPS-ссылка на страницу расписания программы на hse.ru.")
        return parse_groups(self._get(program_url).text)
