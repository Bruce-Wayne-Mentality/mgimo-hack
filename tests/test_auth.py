"""Sign-in, sessions and access gate (C1: FR-AUTH-1..5, FR-PRF-1, section 10).

Runs on SQLite by default; set TEST_DATABASE_URL to a disposable PostgreSQL
database to run the same checks there (all tables in it are dropped).
"""

import asyncio
import os
import shutil
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select, text

from hse_schedule.accounts.models import AuditLog, User, UserSession
from hse_schedule.accounts.router import AuthSettings
from hse_schedule.accounts.seed import DEMO_ACCOUNTS, seed_demo
from hse_schedule.accounts.service import AuthService
from hse_schedule.api import create_app
from hse_schedule.db import Base, Database
from hse_schedule.directory import StudentDirectory
from hse_schedule.migrate import upgrade
from hse_schedule.notification_store import NotificationStore
from hse_schedule.service import FixtureSource, ScheduleService
from hse_schedule.web import safe_next

ROOT = Path(__file__).resolve().parents[1]
ANNA = {"login": "student.anna", "password": "Demo-Anna-2026"}
BORIS = {"login": "student.boris", "password": "Demo-Boris-2026"}
STAFF = {"login": "staff.deanery", "password": "Demo-Staff-2026"}
SECRET = b"test-secret-" + b"x" * 32
COOKIE = "__Host-session"


def reset_postgres(url: str) -> None:
    async def drop() -> None:
        database = Database(url, pooled=False)
        async with database.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.execute(text("DROP TABLE IF EXISTS alembic_version"))
        await database.dispose()

    asyncio.run(drop())


class AuthTestCase(unittest.TestCase):
    demo = True

    def setUp(self):
        self.temporary = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.temporary, ignore_errors=True)
        self.url = os.environ.get("TEST_DATABASE_URL") or f"sqlite:///{(self.temporary / 'app.sqlite3').as_posix()}"
        if os.environ.get("TEST_DATABASE_URL"):
            reset_postgres(self.url)
        upgrade(self.url)  # the schema always comes from the real migrations
        self.database = Database(self.url, pooled=False)
        asyncio.run(seed_demo(self.database))
        self.now = datetime(2026, 11, 13, 9, 0, tzinfo=timezone.utc)
        self.auth = AuthService(self.database, clock=lambda: self.now)

        dist = self.temporary / "dist"
        (dist / "assets").mkdir(parents=True)
        (dist / "index.html").write_text("<!doctype html><div id=root></div>", encoding="utf-8")
        (dist / "sw.js").write_text("self.addEventListener('push', () => {});", encoding="utf-8")
        (dist / "assets" / "app.js").write_text("console.log('app')", encoding="utf-8")
        service = ScheduleService(
            StudentDirectory.from_file(ROOT / "examples/students.json"),
            FixtureSource(ROOT / "examples/lessons.json"),
        )
        self.app = create_app(
            service, {}, demo=self.demo,
            notification_store=NotificationStore(self.temporary / "notifications.sqlite3"),
            auth=self.auth,
            auth_settings=AuthSettings(secret=SECRET, demo=self.demo),
            demo_accounts=DEMO_ACCOUNTS,
            web_dist=dist,
        )
        self.client = self.new_client()

    def new_client(self, ip="203.0.113.10"):
        return TestClient(self.app, base_url="https://testserver", client=(ip, 50000), follow_redirects=False)

    def login(self, client=None, account=ANNA, **extra):
        client = client or self.client
        return client.post("/api/auth/login", json={**account, **extra})

    def signed_in(self, account=ANNA, **extra):
        client = self.new_client()
        response = self.login(client, account, **extra)
        self.assertEqual(response.status_code, 200, response.text)
        client.headers["X-CSRF-Token"] = response.json()["csrf_token"]
        return client

    def query(self, statement):
        async def run():
            async with self.database.session() as db:
                return (await db.execute(statement)).scalars().all()

        return asyncio.run(run())


class LoginTests(AuthTestCase):
    def test_login_sets_hardened_session_cookie_and_returns_csrf(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["user"]["login"], "student.anna")
        self.assertEqual(body["user"]["role"], "student")
        self.assertEqual(body["user"]["display_name"], "Анна Сергеевна Миронова")
        self.assertTrue(body["csrf_token"])
        cookie = response.headers["set-cookie"]
        self.assertTrue(cookie.startswith(f"{COOKIE}="))
        for attribute in ("HttpOnly", "Secure", "SameSite=lax", "Path=/"):
            self.assertIn(attribute.lower(), cookie.lower())
        self.assertNotIn("max-age", cookie.lower())  # without "remember me": browser session
        self.assertNotIn(response.cookies[COOKIE], response.text)

    def test_database_keeps_only_hashes(self):
        response = self.login()
        token = response.cookies[COOKIE]
        hashes = self.query(select(User.password_hash))
        self.assertTrue(all(value.startswith("$argon2id$") for value in hashes))
        self.assertNotIn(ANNA["password"], " ".join(hashes))
        sessions = self.query(select(UserSession.token_hash))
        self.assertEqual(len(sessions), 1)
        self.assertNotEqual(sessions[0], token)
        self.assertEqual(len(sessions[0]), 64)

    def test_unknown_login_and_wrong_password_are_indistinguishable(self):
        wrong = self.login(account={"login": "student.anna", "password": "not-the-password"})
        unknown = self.login(account={"login": "nobody.here", "password": "not-the-password"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.status_code, unknown.status_code)
        self.assertEqual(wrong.json(), unknown.json())
        self.assertEqual(wrong.json()["error"]["code"], "invalid_credentials")
        self.assertNotIn("set-cookie", wrong.headers)

    def test_login_ignores_case_and_surrounding_spaces(self):
        response = self.login(account={"login": "  Student.ANNA ", "password": ANNA["password"]})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.login(account={"login": "student.anna", "password": "demo-anna-2026"}).status_code, 401)

    def test_validation_errors_use_the_documented_format(self):
        response = self.client.post("/api/auth/login", json={"login": "", "password": "x", "extra": 1})
        self.assertEqual(response.status_code, 422)
        error = response.json()["error"]
        self.assertEqual(error["code"], "validation_failed")
        self.assertIn("login", error["fields"])

    def test_five_failures_lock_login_and_ip_pair_for_fifteen_minutes(self):
        for _ in range(4):
            self.assertEqual(self.login(account={**ANNA, "password": "wrong-password"}).status_code, 401)
        fifth = self.login(account={**ANNA, "password": "wrong-password"})
        self.assertEqual(fifth.status_code, 429)
        locked = self.login()  # even the right password is refused now
        self.assertEqual(locked.status_code, 429)
        self.assertEqual(locked.json()["error"]["code"], "too_many_attempts")
        self.assertTrue(int(locked.headers["Retry-After"]) > 0)
        self.assertNotIn("set-cookie", locked.headers)
        # Another address and another login are unaffected.
        self.assertEqual(self.login(self.new_client("198.51.100.7")).status_code, 200)
        self.assertEqual(self.login(account=BORIS).status_code, 200)
        self.now += timedelta(minutes=15, seconds=1)
        self.assertEqual(self.login().status_code, 200)
        actions = self.query(select(AuditLog.action))
        self.assertIn("auth.login_locked", actions)
        self.assertIn("auth.login_failed", actions)

    def test_unknown_login_is_locked_the_same_way(self):
        for _ in range(5):
            response = self.login(account={"login": "ghost", "password": "wrong-password"})
        self.assertEqual(response.status_code, 429)

    def test_failures_spread_over_time_do_not_lock(self):
        for _ in range(8):
            self.assertEqual(self.login(account={**ANNA, "password": "wrong-password"}).status_code, 401)
            self.now += timedelta(minutes=4)
            if _ % 3 == 2:
                self.now += timedelta(minutes=10)
        self.assertEqual(self.login().status_code, 200)

    def test_success_resets_the_pair_counter(self):
        for _ in range(4):
            self.login(account={**ANNA, "password": "wrong-password"})
        self.assertEqual(self.login().status_code, 200)
        for _ in range(4):
            self.assertEqual(self.login(account={**ANNA, "password": "wrong-password"}).status_code, 401)

    def test_one_address_cannot_spray_many_logins(self):
        responses = [
            self.login(account={"login": f"user{index}", "password": "wrong-password"}).status_code
            for index in range(30)
        ]
        self.assertEqual(responses[-1], 429)
        self.assertEqual(self.login(account=BORIS).status_code, 429)
        self.assertEqual(self.login(self.new_client("198.51.100.7"), BORIS).status_code, 200)

    def test_inactive_account_cannot_sign_in_and_loses_sessions(self):
        client = self.signed_in()

        async def deactivate():
            async with self.database.session() as db:
                user = await db.scalar(select(User).where(User.login == "student.anna"))
                user.is_active = False
                await db.commit()

        asyncio.run(deactivate())
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.login().status_code, 401)


class SessionTests(AuthTestCase):
    def test_me_returns_user_and_csrf_but_requires_a_session(self):
        anonymous = self.client.get("/api/auth/me")
        self.assertEqual(anonymous.status_code, 401)
        self.assertEqual(anonymous.json()["error"]["code"], "unauthorized")
        client = self.signed_in()
        response = client.get("/api/auth/me")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user"]["login"], "student.anna")
        self.assertEqual(response.json()["csrf_token"], client.headers["X-CSRF-Token"])
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")

    def test_session_expires_after_twelve_idle_hours(self):
        client = self.signed_in()
        self.now += timedelta(hours=11, minutes=59)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)  # activity extends it
        self.now += timedelta(hours=11, minutes=59)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)
        self.now += timedelta(hours=12, seconds=1)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.query(select(UserSession.id)), [])

    def test_remember_me_keeps_session_for_thirty_days(self):
        client = self.new_client()
        response = self.login(client, remember=True)
        self.assertIn(f"max-age={30 * 24 * 3600}", response.headers["set-cookie"].lower())
        self.now += timedelta(days=29)
        self.assertEqual(client.get("/api/auth/me").status_code, 200)
        self.now += timedelta(days=30, seconds=1)
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_tampered_or_foreign_cookie_is_rejected(self):
        client = self.new_client()
        client.cookies.set(COOKIE, "forged-token", domain="testserver")
        self.assertEqual(client.get("/api/auth/me").status_code, 401)

    def test_logout_requires_csrf_and_removes_the_server_session(self):
        client = self.signed_in()
        token = client.cookies.get(COOKIE)
        without = client.post("/api/auth/logout", headers={"X-CSRF-Token": ""})
        self.assertEqual(without.status_code, 403)
        self.assertEqual(without.json()["error"]["code"], "csrf_failed")
        response = client.post("/api/auth/logout")
        self.assertEqual(response.status_code, 204)
        self.assertIn(f'{COOKIE}=""', response.headers["set-cookie"])
        replay = self.new_client()
        replay.cookies.set(COOKIE, token, domain="testserver")
        self.assertEqual(replay.get("/api/auth/me").status_code, 401)

    def test_logout_everywhere_ends_all_devices(self):
        phone, laptop = self.signed_in(), self.signed_in()
        self.assertEqual(phone.post("/api/auth/logout-all").status_code, 204)
        self.assertEqual(laptop.get("/api/auth/me").status_code, 401)
        self.assertEqual(phone.get("/api/auth/me").status_code, 401)

    def test_new_login_on_same_browser_replaces_previous_session(self):
        client = self.signed_in()
        self.assertEqual(self.login(client, BORIS).status_code, 200)
        self.assertEqual(len(self.query(select(UserSession.id))), 1)
        self.assertEqual(client.get("/api/auth/me").json()["user"]["login"], "student.boris")

    def test_password_change_rules_and_other_sessions_end(self):
        current, other = self.signed_in(), self.signed_in()
        short = current.post("/api/auth/password", json={"current_password": ANNA["password"], "new_password": "short"})
        self.assertEqual(short.status_code, 422)
        self.assertIn("new_password", short.json()["error"]["fields"])
        wrong = current.post("/api/auth/password", json={"current_password": "wrong", "new_password": "long enough pass"})
        self.assertEqual(wrong.status_code, 422)
        self.assertIn("current_password", wrong.json()["error"]["fields"])
        no_csrf = current.post(
            "/api/auth/password",
            json={"current_password": ANNA["password"], "new_password": "long enough pass"},
            headers={"X-CSRF-Token": "nope"},
        )
        self.assertEqual(no_csrf.status_code, 403)
        changed = current.post("/api/auth/password", json={"current_password": ANNA["password"], "new_password": "длинный пароль"})
        self.assertEqual(changed.status_code, 204)
        self.assertEqual(current.get("/api/auth/me").status_code, 200)
        self.assertEqual(other.get("/api/auth/me").status_code, 401)
        self.assertEqual(self.login().status_code, 401)
        self.assertEqual(self.login(account={**ANNA, "password": "длинный пароль"}).status_code, 200)
        self.assertIn("auth.password_changed", self.query(select(AuditLog.action)))


class ProfileAndAccessTests(AuthTestCase):
    def test_profile_belongs_to_session_owner_only(self):
        anna, boris = self.signed_in(ANNA), self.signed_in(BORIS)
        profile = anna.get("/api/me/profile", params={"user_id": "anything", "login": "student.boris"}).json()
        self.assertEqual(profile["full_name"], "Анна Сергеевна Миронова")
        self.assertEqual(profile["record_book_no"], "DEMO-250114")
        self.assertEqual(profile["course"], 2)
        self.assertEqual(profile["program"]["code"], "38.03.01")
        for field in ("faculty", "group", "study_form", "status", "contacts"):
            self.assertIn(field, profile)
        other = boris.get("/api/me/profile").json()
        self.assertEqual(other["full_name"], "Борис Андреевич Лебедев")
        self.assertNotIn("Миронова", boris.get("/api/me/profile").text)
        self.assertEqual(self.client.get("/api/me/profile").status_code, 401)

    def test_schedule_is_resolved_from_the_session(self):
        anna, boris = self.signed_in(ANNA), self.signed_in(BORIS)
        dates = {"start": "2026-11-09", "finish": "2026-11-15", "email": "boris@demo-university.test"}
        anna_lessons = {item["source_lesson_id"] for item in anna.get("/api/me/schedule", params=dates).json()["lessons"]}
        boris_lessons = {item["source_lesson_id"] for item in boris.get("/api/me/schedule", params=dates).json()["lessons"]}
        self.assertEqual(anna_lessons & boris_lessons, {"90001", "90004"})
        self.assertNotEqual(anna_lessons, boris_lessons)
        self.assertEqual(self.client.get("/api/me/schedule", params=dates).status_code, 401)

    def test_staff_account_has_profile_but_no_student_schedule(self):
        staff = self.signed_in(STAFF)
        profile = staff.get("/api/me/profile").json()
        self.assertEqual(profile["kind"], "staff")
        response = staff.get("/api/me/schedule", params={"start": "2026-11-09", "finish": "2026-11-15"})
        self.assertEqual(response.status_code, 404)

    def test_changing_requests_with_a_cookie_need_the_csrf_header(self):
        client = self.signed_in()
        refused = client.patch("/api/me/notification-settings", json={"enabled": True}, headers={"X-CSRF-Token": ""})
        self.assertEqual(refused.status_code, 403)
        accepted = client.patch("/api/me/notification-settings", json={"enabled": True})
        self.assertEqual(accepted.status_code, 200)
        self.assertTrue(client.get("/api/me/notification-settings").json()["enabled"])

    def test_csrf_token_of_another_session_is_useless(self):
        anna, boris = self.signed_in(ANNA), self.signed_in(BORIS)
        response = anna.post("/api/auth/logout", headers={"X-CSRF-Token": boris.headers["X-CSRF-Token"]})
        self.assertEqual(response.status_code, 403)

    def test_demo_accounts_listed_in_demo_mode(self):
        accounts = self.client.get("/api/auth/demo-accounts").json()["accounts"]
        self.assertIn({"login": "student.anna", "password": "Demo-Anna-2026", "description": "Студент А · 2 курс"}, accounts)
        self.assertEqual(len(accounts), 5)


class LiveModeTests(AuthTestCase):
    demo = False

    def test_demo_accounts_hidden_outside_demo(self):
        self.assertEqual(self.client.get("/api/auth/demo-accounts").status_code, 404)


class PageGateTests(AuthTestCase):
    def test_every_screen_redirects_to_login_without_session(self):
        root = self.client.get("/")
        self.assertEqual(root.status_code, 303)
        self.assertEqual(root.headers["location"], "/login")
        deep = self.client.get("/schedule", params={"week": "2"})
        self.assertEqual(deep.status_code, 303)
        self.assertEqual(deep.headers["location"], "/login?next=/schedule%3Fweek%3D2")
        for path in ("/profile", "/requests/42", "/notifications"):
            self.assertEqual(self.client.get(path).status_code, 303, path)

    def test_login_screen_is_public_and_the_first_page(self):
        response = self.client.get("/login")
        self.assertEqual(response.status_code, 200)
        self.assertIn('id=root', response.text)
        self.assertEqual(response.headers["Cache-Control"], "no-cache")

    def test_signed_in_user_gets_the_app_and_skips_login(self):
        client = self.signed_in()
        self.assertEqual(client.get("/").status_code, 200)
        self.assertEqual(client.get("/schedule").status_code, 200)
        again = client.get("/login", params={"next": "/schedule"})
        self.assertEqual(again.status_code, 303)
        self.assertEqual(again.headers["location"], "/schedule")
        hostile = client.get("/login", params={"next": "//evil.example/path"})
        self.assertEqual(hostile.headers["location"], "/")

    def test_static_assets_and_service_worker_stay_public(self):
        self.assertEqual(self.client.get("/assets/app.js").status_code, 200)
        worker = self.client.get("/sw.js")
        self.assertEqual(worker.status_code, 200)
        self.assertEqual(worker.headers["Service-Worker-Allowed"], "/")

    def test_unknown_api_paths_are_json_404_not_the_app(self):
        response = self.client.get("/api/does-not-exist")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("id=root", response.text)
        self.assertEqual(self.client.get("/../pyproject.toml").status_code, 303)

    def test_security_headers_on_pages_and_api(self):
        for path in ("/login", "/api/auth/me"):
            headers = self.client.get(path).headers
            csp = headers["Content-Security-Policy"]
            self.assertIn("script-src 'self'", csp)
            self.assertNotIn("unsafe-inline", csp)
            self.assertIn("frame-ancestors 'none'", csp)
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")

    def test_safe_next_only_allows_local_paths(self):
        self.assertEqual(safe_next("/schedule?week=2"), "/schedule?week=2")
        for hostile in (None, "", "https://evil.example", "//evil.example", "/\\evil.example", "javascript:alert(1)", "/login"):
            self.assertEqual(safe_next(hostile), "/", hostile)


if __name__ == "__main__":
    unittest.main()
