import unittest
from datetime import date

import httpx

from hse_schedule.client import HSEClient
from hse_schedule.errors import InvalidPayload, SourceUnavailable


START = date(2026, 11, 9)
FINISH = date(2026, 11, 15)


class HSEClientTests(unittest.TestCase):
    def client(self, handler):
        return HSEClient(transport=httpx.MockTransport(handler))

    def test_group_query_matches_the_public_portal_contract(self):
        def handler(request):
            self.assertEqual(str(request.url.copy_with(query=None)), "https://www.hse.ru/api/timetable/lessons")
            self.assertEqual(dict(request.url.params), {
                "groupoid": "88229", "receiverType": "3",
                "fromdate": "2026.11.09", "todate": "2026.11.15",
            })
            return httpx.Response(200, json={"Lessons": [], "StatusCode": {"Code": 0}})
        self.assertEqual(self.client(handler).schedule(start=START, finish=FINISH, group_oid="88229"), ())

    def test_individual_query_uses_student_oid_not_email(self):
        def handler(request):
            self.assertEqual(request.url.params["studentoid"], "123")
            self.assertEqual(request.url.params["receiverType"], "0")
            self.assertNotIn("email", request.url.params)
            return httpx.Response(200, json=[])
        self.client(handler).schedule(start=START, finish=FINISH, student_oid="123")

    def test_subject_and_range_are_validated_before_network(self):
        def handler(_request):
            self.fail("Unexpected upstream request")
        for subject in ({}, {"student_oid": "1", "group_oid": "2"}, {"group_oid": "0"}, {"group_oid": "1/path"}):
            with self.subTest(subject=subject), self.assertRaises(ValueError):
                self.client(handler).schedule(start=START, finish=FINISH, **subject)
        with self.assertRaises(ValueError):
            self.client(handler).schedule(start=FINISH, finish=START, group_oid="1")

    def test_redirect_html_and_http_errors_raise_unavailable(self):
        responses = (
            httpx.Response(302, headers={"Location": "https://www.hse.ru/eduland/schedule/"}),
            httpx.Response(200, text="<html>login</html>", headers={"Content-Type": "text/html"}),
            httpx.Response(200, text="<html>login</html>"),
            httpx.Response(403), httpx.Response(502),
        )
        for response in responses:
            with self.subTest(status=response.status_code), self.assertRaises(SourceUnavailable):
                self.client(lambda _: response).schedule(start=START, finish=FINISH, group_oid="1")

    def test_timeout_is_controlled(self):
        def handler(request):
            raise httpx.ReadTimeout("timeout", request=request)
        with self.assertRaises(SourceUnavailable):
            self.client(handler).schedule(start=START, finish=FINISH, group_oid="1")

    def test_malformed_json_raises_invalid_payload(self):
        with self.assertRaises(InvalidPayload):
            self.client(lambda _: httpx.Response(200, text="{broken")).schedule(start=START, finish=FINISH, group_oid="1")

    def test_upstream_extra_dates_are_excluded(self):
        def row(day):
            return {"date": day, "discipline": "Демо", "beginLesson": "09:30", "endLesson": "10:50"}
        lessons = self.client(lambda _: httpx.Response(200, json=[row("2026.11.09"), row("2026.11.16")])).schedule(
            start=START, finish=FINISH, group_oid="1"
        )
        self.assertEqual(len(lessons), 1)
        self.assertEqual(lessons[0].date, START)

    def test_programme_group_selector(self):
        client = self.client(lambda _: httpx.Response(200, text="<option data-groups='[[\"Демо\",\"1000\"]]'>1</option>"))
        self.assertEqual(client.groups("https://www.hse.ru/ba/ami/timetable")[0].oid, "1000")
        for url in ("http://www.hse.ru/ba/ami/timetable", "https://hse.ru.evil.test/timetable", "https://user@www.hse.ru/timetable"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                client.groups(url)


if __name__ == "__main__":
    unittest.main()
