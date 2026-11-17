"""«Красная кнопка» by the specification: stage 1 verdicts, encrypted buffer and registry,
the canary (no text in logs or in plain form in the database), privacy levels,
conflict of interest, statuses and SLA, stage 2 with a fake GigaChat."""

import asyncio
import logging
import unittest
import uuid

from sqlalchemy import select, text

from hse_schedule.accounts.models import User
from hse_schedule.db import Base
from hse_schedule.gigachat import ChatResult, GigaChatUnavailable
from hse_schedule.redbutton import stage1
from hse_schedule.redbutton.crypto import KeyStore
from hse_schedule.redbutton.models import Complaint, ModerationBuffer
from hse_schedule.redbutton.service import RedButtonService

from tests.test_features import ADMIN, ANNA, BORIS, STAFF, VERA, FeatureTestCase

CANARY = "КАНАРЕЙКА-7f3a"
GOOD = "Преподаватель снизил оценку за контрольную в четверг без объяснений, прошу пересмотреть работу и показать критерии."


class Stage1Tests(unittest.TestCase):
    def test_obscenity_with_homoglyphs_and_separators(self):
        for sample in ("Это полный пиздец с оценками на паре", "методист требует xyйню вторую неделю на паре",
                       "п и з д е ц какой-то с расписанием"):
            result = stage1.check(sample + " в деканате, прошу разобраться с ситуацией.")
            self.assertEqual(result.verdict, "REJECT_OBSCENE", sample)
            self.assertTrue(result.spans)

    def test_allowlist_and_sharp_criticism_pass(self):
        result = stage1.check("Это оскорбление студентов: страховать нас никто не хочет, хлеб в столовой чёрствый, "
                              "преподаватель несправедливо и хамски занизил оценку, прошу разобраться.")
        self.assertEqual(result.verdict, "ACCEPT")

    def test_gibberish_asks_details_and_threat_escalates(self):
        self.assertEqual(stage1.check("ыврпаол ывапролд ывапрол ывапр олдывап").verdict, "ASK_DETAILS")
        threat = stage1.check("Если он ещё раз так сделает, я его убью, оценку занизил на экзамене вчера.")
        self.assertEqual((threat.verdict, threat.risk), ("ESCALATE", "threat"))
        self.assertEqual(stage1.check("Мне очень тяжело, не хочу жить после этой сессии, никто не помогает.").risk, "self_harm")

    def test_personal_data_masked(self):
        masked = stage1.mask_pdn("Я Анна Миронова, пишите anna@demo.test или +7 900 000-00-01", names=["Анна Сергеевна Миронова"])
        self.assertNotIn("Анна", masked)
        self.assertNotIn("anna@", masked)
        self.assertNotIn("900", masked)


class KeyStoreTests(unittest.TestCase):
    def test_day_key_shredding_makes_buffer_unreadable(self):
        import tempfile
        from datetime import date, timedelta

        keys = KeyStore(tempfile.mkdtemp())
        day = date(2026, 11, 1)
        key_id, nonce, ct = keys.seal_buffer("секрет", day, "s1")
        self.assertEqual(keys.open_buffer(key_id, nonce, ct, "s1"), "секрет")
        self.assertEqual(keys.purge_day_keys(day + timedelta(days=16)), 1)
        fresh = KeyStore(keys.dir)
        self.assertIsNone(fresh.open_buffer(key_id, nonce, ct, "s1"))


class RedButtonApiTests(FeatureTestCase):
    def post(self, account, body):
        return self.client(account).post("/api/complaints", json={"privacy": "confidential", "type": "unfair", **body})

    def all_rows(self) -> str:
        async def dump():
            out = []
            async with self.database.session() as db:
                for table in Base.metadata.sorted_tables:
                    for row in (await db.execute(table.select())).all():
                        for value in row:
                            out.append(value.decode("utf-8", "ignore") if isinstance(value, (bytes, bytearray)) else str(value))
            return "\n".join(out)

        return asyncio.run(dump())

    def test_obscene_is_returned_and_never_reaches_the_registry(self):
        response = self.post(VERA, {"text": "Методист деканата требует какую-то xyйню, справку не выдают вторую неделю, прошу помочь."})
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["verdict"], "REJECT_OBSCENE")
        self.assertTrue(body["spans"])
        manual = self.client(VERA).post("/api/complaints/manual-review", json={"session_id": body["session_id"]})
        self.assertEqual(manual.status_code, 409)
        self.assertNotIn("xyйню", self.all_rows())  # buffer holds ciphertext only

    def test_ask_details_three_times_then_manual_review(self):
        session = None
        for attempt in range(3):
            body = {"text": "ыврпаол ывапролд ывапрол ывапр олдывап ыврпаол"}
            if session:
                body["session_id"] = session
            response = self.post(VERA, body).json()
            self.assertEqual(response["verdict"], "ASK_DETAILS")
            session = response["session_id"]
        self.assertTrue(response["can_manual_review"])
        created = self.client(VERA).post("/api/complaints/manual-review", json={"session_id": session})
        self.assertEqual(created.status_code, 201, created.text)
        self.assertEqual(created.json()["status"], "MODERATION")

        async def left():
            async with self.database.session() as db:
                return (await db.scalars(select(ModerationBuffer).where(ModerationBuffer.session_id == uuid.UUID(session)))).all()

        self.assertEqual(asyncio.run(left()), [])

    def test_canary_is_not_in_logs_or_plain_database(self):
        captured = []

        class Grab(logging.Handler):
            def emit(self, record):
                captured.append(record.getMessage())

        handler = Grab(level=logging.DEBUG)
        root = logging.getLogger()
        old_level = root.level
        root.addHandler(handler)
        root.setLevel(logging.DEBUG)
        try:
            response = self.post(BORIS, {"text": f"{GOOD} Код для проверки: {CANARY}.", "category": "grades"})
        finally:
            root.removeHandler(handler)
            root.setLevel(old_level)
        self.assertEqual(response.status_code, 201, response.text)
        complaint = response.json()["complaint"]
        self.assertIn(CANARY, complaint["text"])  # the owner reads it back (decrypted)…
        self.assertFalse(any(CANARY in line for line in captured))  # …it never reached a log…
        self.assertNotIn(CANARY, self.all_rows())  # …and nothing in the database holds it in plain form

    def test_privacy_levels_and_isolation(self):
        anonymous = self.post(ANNA, {"text": GOOD, "privacy": "anonymous", "category": "grades"}).json()["complaint"]
        named = self.post(ANNA, {"text": GOOD, "privacy": "named", "category": "grades"}).json()["complaint"]
        confidential = self.post(ANNA, {"text": GOOD, "privacy": "confidential", "category": "grades"}).json()["complaint"]
        mine = {item["id"] for item in self.client(ANNA).get("/api/complaints").json()["items"]}
        self.assertTrue({anonymous["id"], named["id"], confidential["id"]} <= mine)  # anonymous ones too
        self.assertEqual(self.client(BORIS).get(f"/api/complaints/{anonymous['id']}").status_code, 404)
        staff, curator = self.client(STAFF), self.client(ADMIN)
        authors = {
            key: (staff.get(f"/api/staff/complaints/{item['id']}").json()["author"],
                  curator.get(f"/api/staff/complaints/{item['id']}").json()["author"])
            for key, item in (("anonymous", anonymous), ("named", named), ("confidential", confidential))
        }
        self.assertEqual(authors["anonymous"], ("Аноним", "Аноним"))
        self.assertTrue(authors["named"][0].startswith("Анна"))
        self.assertTrue(authors["confidential"][0].startswith("Студент #"))
        self.assertTrue(authors["confidential"][1].startswith("Анна"))

        async def anonymous_row():
            async with self.database.session() as db:
                return await db.get(Complaint, uuid.UUID(anonymous["id"]))

        row = asyncio.run(anonymous_row())
        anna_id = asyncio.run(self._user_id("student.anna"))
        self.assertNotEqual(row.author_ref, str(anna_id))

        async def author_rows():
            async with self.database.session() as db:
                return (await db.execute(text("SELECT user_id FROM complaint_authors WHERE complaint_id = :c"),
                                         {"c": row.id if self.url.startswith("postgres") else row.id.hex})).all()

        self.assertEqual(asyncio.run(author_rows()), [])  # anonymous: no link to the account is stored

    async def _user_id(self, login):
        async with self.database.session() as db:
            return await db.scalar(select(User.id).where(User.login == login))

    def test_subject_of_a_complaint_never_sees_it(self):
        curator_items = self.client(ADMIN).get("/api/staff/complaints").json()["items"]
        about_staff = next(item for item in curator_items if item["link_label"] and item["link_label"].startswith("Заявка"))
        staff_ids = {item["id"] for item in self.client(STAFF).get("/api/staff/complaints").json()["items"]}
        self.assertNotIn(about_staff["id"], staff_ids)
        self.assertEqual(self.client(STAFF).get(f"/api/staff/complaints/{about_staff['id']}").status_code, 404)

    def test_full_status_flow_with_one_escalation(self):
        created = self.post(BORIS, {"text": GOOD, "privacy": "named", "category": "grades"}).json()["complaint"]
        cid = created["id"]
        staff, curator, boris = self.client(STAFF), self.client(ADMIN), self.client(BORIS)
        act = lambda client, action, text=None: client.post(f"/api/staff/complaints/{cid}/status", json={"action": action, "text": text})  # noqa: E731
        self.assertEqual(act(staff, "answer", "рано").status_code, 409)
        self.assertEqual(act(staff, "take").json()["status"], "IN_PROGRESS")
        self.assertEqual(act(staff, "need_info", "Пришлите номер варианта контрольной.").json()["status"], "NEED_INFO")
        self.assertEqual(boris.post(f"/api/complaints/{cid}/messages", json={"text": "Вариант 3."}).json()["status"], "IN_PROGRESS")
        self.assertEqual(act(staff, "answer", "Кафедра перепроверила: +3 балла.").json()["status"], "ANSWERED")
        self.assertEqual(boris.post(f"/api/complaints/{cid}/feedback", json={"resolved": False, "comment": "Не согласен, задача решена полностью."}).json()["status"], "ESCALATED")
        self.assertEqual(act(staff, "take").status_code, 409)  # the next level is the curator
        self.assertEqual(act(curator, "take").json()["status"], "IN_PROGRESS")
        act(curator, "answer", "Комиссия подтвердила решение кафедры.")
        again = boris.post(f"/api/complaints/{cid}/feedback", json={"resolved": False, "comment": "Всё равно не согласен с решением."})
        self.assertEqual(again.status_code, 409)
        self.assertEqual(boris.post(f"/api/complaints/{cid}/feedback", json={"resolved": True}).json()["status"], "CLOSED")
        texts = [m["body"] for m in boris.get(f"/api/complaints/{cid}").json()["messages"]]
        self.assertIn("Вариант 3.", texts)

    def test_withdraw_only_while_new_and_text_is_gone(self):
        created = self.post(VERA, {"text": GOOD, "category": "grades"}).json()["complaint"]
        self.assertEqual(self.client(VERA).delete(f"/api/complaints/{created['id']}").status_code, 204)
        after = self.client(VERA).get(f"/api/complaints/{created['id']}").json()
        self.assertEqual((after["status"], after["text"]), ("WITHDRAWN", None))
        self.assertEqual(self.client(VERA).delete(f"/api/complaints/{created['id']}").status_code, 409)

    def test_threat_goes_to_moderation_and_self_harm_gets_help(self):
        threat = self.post(VERA, {"text": "Если он ещё раз так сделает, я его убью, оценку занизил на экзамене вчера."}).json()
        self.assertEqual((threat["verdict"], threat["complaint"]["status"]), ("ESCALATE", "MODERATION"))
        help_ = self.post(VERA, {"text": "Мне очень тяжело, не хочу жить после этой сессии, никто не помогает в деканате."}).json()
        self.assertIn("help", help_)
        moderation = self.client(ADMIN).get("/api/staff/moderation").json()["items"]
        self.assertIn(threat["complaint"]["id"], [item["id"] for item in moderation])
        self.assertEqual(self.client(STAFF).get("/api/staff/moderation").status_code, 403)
        self.assertEqual(self.client(STAFF).get(f"/api/staff/complaints/{threat['complaint']['id']}").status_code, 404)
        accepted = self.client(ADMIN).post(f"/api/staff/complaints/{threat['complaint']['id']}/status", json={"action": "accept"})
        self.assertEqual(accepted.json()["status"], "NEW")


class FakeGiga:
    model = "fake"

    def __init__(self, answers):
        self.answers = list(answers)
        self.seen = []

    async def chat_json(self, system, user, schema, **kwargs):
        self.seen.append(user)
        answer = self.answers.pop(0)
        if isinstance(answer, Exception):
            raise answer
        return ChatResult(data=answer, latency_ms=5, tokens=900, model="fake")


AI = {"meaningful": True, "missing": [], "insult": "none", "veiled_obscenity": False, "risk": "none", "category": "documents",
      "subject_type": "procedure", "title": "Задержка справки", "summary": "Студент просит ускорить справку.", "urgency": 3,
      "confidence": 0.9}


class Stage2Tests(FeatureTestCase):
    def service(self, answers) -> tuple[RedButtonService, FakeGiga]:
        fake = FakeGiga(answers)
        return RedButtonService(self.database, keys=KeyStore(), gigachat=fake), fake

    def user(self, login) -> User:
        async def get():
            async with self.database.session() as db:
                return await db.scalar(select(User).where(User.login == login))

        return asyncio.run(get())

    def submit(self, service, text_):
        anna = self.user("student.anna")

        async def run():
            status, body = await service.submit(anna, {"privacy": "named"}, text_)
            await asyncio.gather(*list(service._tasks))
            async with self.database.session() as db:
                return await db.get(Complaint, uuid.UUID(body["complaint"]["id"]))

        return asyncio.run(run())

    def test_clean_labels_enrich_and_masking(self):
        service, fake = self.service([AI])
        row = self.submit(service, "Я Анна Миронова, anna@demo-university.test. Справку для стажировки не выдают вторую неделю, прошу ускорить.")
        self.assertEqual((row.status, row.category, row.category_source, row.title, row.priority), ("NEW", "documents", "ai", "Задержка справки", 1))
        self.assertNotIn("Миронова", fake.seen[0])
        self.assertNotIn("anna@", fake.seen[0])

    def test_insult_goes_to_curator(self):
        service, _ = self.service([AI | {"insult": "person", "confidence": 0.9}])
        row = self.submit(service, "Методист — полное ничтожество, справку не выдают вторую неделю, прошу разобраться с этим.")
        self.assertEqual((row.status, row.moderation_reason), ("MODERATION", "ai_insult"))

    def test_unavailable_three_times_then_manual(self):
        service, _ = self.service([GigaChatUnavailable("x")] * 3)
        row = self.submit(service, GOOD)
        self.assertEqual((row.stage2_state, row.stage2_attempts, row.status), ("pending", 1, "NEW"))

        async def retry():
            for _ in range(2):
                async with self.database.session() as db:
                    c = await db.get(Complaint, row.id)
                    c.stage2_next_at = c.created_at
                    await db.commit()
                await service._stage2(row.id)
            async with self.database.session() as db:
                return await db.get(Complaint, row.id)

        final = asyncio.run(retry())
        self.assertEqual((final.stage2_state, final.status, final.moderation_reason), ("failed", "MODERATION", "ai_unavailable"))


if __name__ == "__main__":
    unittest.main()
