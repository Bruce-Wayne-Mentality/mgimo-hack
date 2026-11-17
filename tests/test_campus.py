"""Benchmark upgrades: global search, free rooms now, teachers, canteen, room finder, scholarship forecast."""

import unittest

from hse_schedule.academics.service import scholarship_forecast
from hse_schedule.campus import room_location

from tests.test_features import ANNA, BORIS, STAFF, VERA, FeatureTestCase


class RoomFinderTests(unittest.TestCase):
    def test_room_codes(self):
        self.assertEqual((room_location("Б-118")["building"], room_location("Б-118")["floor"]), ("Б", 1))
        self.assertEqual(room_location("В-404")["floor_text"], "4 этаж")
        self.assertIsNone(room_location("Онлайн"))
        self.assertIsNone(room_location("Z-999"))


class ForecastTests(unittest.TestCase):
    def item(self, form, points, due, pace, level="green"):
        return {"id": form + str(points), "title": form, "control_label": form, "control_form": form,
                "risk": {"level": level, "points": points, "due_weight": due, "pace": pace}}

    def test_status(self):
        keeps = scholarship_forecast([self.item("exam", 32, 40, 0.8), self.item("credit", 35, 40, 0.875)])
        self.assertEqual(keeps["status"], "keeps")
        risk = scholarship_forecast([self.item("exam", 24, 40, 0.6), self.item("credit", 35, 40, 0.875)])
        self.assertEqual(risk["status"], "at_risk")
        blocking = next(r for r in risk["rows"] if r["ok"] is False)
        self.assertEqual(blocking["need"], round((70 - 24) / 60 * 100))
        raised = scholarship_forecast([self.item("exam", 38, 40, 0.95)])
        self.assertEqual(raised["status"], "raised")
        self.assertEqual(scholarship_forecast([self.item("exam", 0, 0, None, "grey")])["status"], "unknown")


class CampusApiTests(FeatureTestCase):
    def test_search_is_scoped_to_the_user(self):
        anna = self.client(ANNA).get("/api/search", params={"q": "эконометр"}).json()
        keys = {g["key"] for g in anna["groups"]}
        self.assertIn("disciplines", keys)
        vera = self.client(VERA).get("/api/search", params={"q": "эконометр"}).json()
        self.assertNotIn("disciplines", {g["key"] for g in vera["groups"]})  # another group's discipline
        certificates = self.client(ANNA).get("/api/search", params={"q": "справка"}).json()
        self.assertIn("requests", {g["key"] for g in certificates["groups"]})
        rooms = self.client(BORIS).get("/api/search", params={"q": "Б-118"}).json()
        self.assertIn("rooms", {g["key"] for g in rooms["groups"]})
        staff = self.client(STAFF).get("/api/search", params={"q": "журнал"}).json()
        self.assertTrue(any(i["link"] == "/staff/grades" for g in staff["groups"] for i in g["items"]))
        self.assertEqual(self.anonymous().get("/api/search", params={"q": "x"}).status_code, 401)

    def test_free_now_teachers_canteen_rooms(self):
        free = self.client(ANNA).get("/api/campus/free-now").json()
        self.assertIn("items", free)
        for item in free["items"]:
            self.assertGreaterEqual(item["minutes"], 20)
        teachers = self.client(ANNA).get("/api/teachers").json()["items"]
        self.assertEqual(len({d["title"] for t in teachers for d in t["disciplines"]}), 6)  # own group only
        self.assertTrue(all(len(t["hours"]) == 2 for t in teachers))
        canteen = self.client(ANNA).get("/api/canteen").json()
        self.assertEqual(len(canteen["canteens"]), 2)
        self.assertEqual(canteen, self.client(BORIS).get("/api/canteen").json())  # deterministic per day
        rooms = self.client(ANNA).get("/api/campus/rooms").json()["buildings"]
        self.assertEqual([b["letter"] for b in rooms], ["А", "Б", "В"])
        self.assertEqual(self.client(ANNA).get("/api/campus/room", params={"code": "Z-1"}).status_code, 404)

    def test_study_overview_has_forecast(self):
        boris = self.client(BORIS).get("/api/study").json()["forecast"]
        self.assertEqual(boris["status"], "at_risk")
        self.assertIn("Корпоративные финансы", [r["title"] for r in boris["rows"] if r["ok"] is False])
        self.assertIn(self.client(ANNA).get("/api/study").json()["forecast"]["status"], ("keeps", "raised"))


if __name__ == "__main__":
    unittest.main()
