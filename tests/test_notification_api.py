import base64
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient

from hse_schedule.api import create_app
from hse_schedule.directory import Student, StudentDirectory
from hse_schedule.notification_api import register_notification_routes


class NotificationAPITests(unittest.TestCase):
    def setUp(self):
        self.service = SimpleNamespace(directory=StudentDirectory([
            Student("alice@example.test", "Алиса", group_oids=("1000",)),
            Student("bob@example.test", "Борис", group_oids=("1001",)),
        ]))
        self.store = Mock()
        self.store.get_settings.return_value = {"enabled": False}
        self.store.set_settings.side_effect = lambda _email, enabled: {"enabled": enabled}
        self.store.list_notifications.return_value = {
            "items": [], "unread_count": 0, "next_before": None
        }
        self.store.mark_read.side_effect = lambda email, identifier, _now: (
            email == "alice@example.test" and identifier == 1
        )
        self.store.mark_all_read.return_value = 3
        self.store.telegram_status.return_value = {"linked": False, "username": None}
        self.push = SimpleNamespace(public_key="public-vapid-key")
        self.bot = SimpleNamespace(get_username=lambda: "UniversityScheduleBot")
        self.app = self.make_app()
        self.client = TestClient(self.app)
        self.headers = {"Authorization": "Bearer alice-token"}

    def make_app(self, *, push=True, telegram=True):
        app = create_app(self.service, {"alice-token": "ALICE@example.test", "bob-token": "bob@example.test"})
        register_notification_routes(
            app, self.service, self.store, app.state.account_dependency,
            push_sender=self.push if push else None,
            telegram_bot=self.bot if telegram else None,
        )
        return app

    def test_all_personal_routes_require_identity(self):
        for method, path, body in (
            ("get", "/api/me/notification-settings", None),
            ("patch", "/api/me/notification-settings", {"enabled": True}),
            ("get", "/api/me/notifications", None),
            ("post", "/api/me/notifications/1/read", None),
            ("post", "/api/me/notifications/read-all", None),
            ("delete", "/api/me/push-subscriptions", {"endpoint": "https://fcm.googleapis.com/a"}),
            ("get", "/api/me/telegram", None),
            ("post", "/api/me/telegram/link", None),
            ("delete", "/api/me/telegram", None),
        ):
            with self.subTest(method=method, path=path):
                response = self.client.request(method, path, json=body)
                self.assertEqual(response.status_code, 401)
                self.assertEqual(response.headers["WWW-Authenticate"], "Bearer")
        self.store.assert_not_called()

    def test_settings_use_canonical_account_and_strict_boolean(self):
        response = self.client.patch(
            "/api/me/notification-settings?email=bob@example.test",
            json={"enabled": True}, headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"enabled": True})
        self.store.set_settings.assert_called_once_with("alice@example.test", True)
        self.assertEqual(response.headers["Cache-Control"], "private, no-store")
        for body in ({"enabled": "true"}, {"enabled": 1}, {}, {"enabled": True, "email": "bob@example.test"}):
            with self.subTest(body=body):
                response = self.client.patch("/api/me/notification-settings", json=body, headers=self.headers)
                self.assertEqual(response.status_code, 422)

    def test_inbox_filters_are_scoped_and_validated(self):
        response = self.client.get(
            "/api/me/notifications?limit=5&before=10&unread_only=true&email=bob@example.test",
            headers=self.headers,
        )
        self.assertEqual(response.status_code, 200)
        self.store.list_notifications.assert_called_once_with(
            "alice@example.test", limit=5, before=10, unread_only=True
        )
        for query in ("limit=0", "limit=101", "before=-1"):
            with self.subTest(query=query):
                self.assertEqual(self.client.get(f"/api/me/notifications?{query}", headers=self.headers).status_code, 422)

    def test_read_other_account_notification_returns_not_found(self):
        owned = self.client.post("/api/me/notifications/1/read", headers=self.headers)
        self.assertEqual(owned.status_code, 200)
        other = self.client.post("/api/me/notifications/1/read", headers={"Authorization": "Bearer bob-token"})
        self.assertEqual(other.status_code, 404)
        missing = self.client.post("/api/me/notifications/99/read", headers=self.headers)
        self.assertEqual(missing.status_code, 404)
        self.assertEqual(self.client.post("/api/me/notifications/read-all", headers=self.headers).json(), {"updated": 3})
        args = self.store.mark_all_read.call_args.args
        self.assertEqual(args[0], "alice@example.test")
        self.assertIsNotNone(args[1].utcoffset())

    def test_public_vapid_key_and_channel_not_configured(self):
        self.assertEqual(self.client.get("/api/push/public-key").json(), {"public_key": "public-vapid-key"})
        client = TestClient(self.make_app(push=False, telegram=False))
        self.assertEqual(client.get("/api/push/public-key").status_code, 503)
        self.assertEqual(client.post("/api/me/telegram/link", headers=self.headers).status_code, 503)

    def test_push_subscription_validation_and_account_scope(self):
        def encoded(value):
            return base64.urlsafe_b64encode(value).decode().rstrip("=")
        subscription = {
            "endpoint": "https://fcm.googleapis.com/fcm/send/example",
            "keys": {"p256dh": encoded(b"\x04" + b"a" * 64), "auth": encoded(b"b" * 16)},
        }
        # Channel validation itself has dedicated tests; exercise API wiring.
        from unittest.mock import patch
        with patch("hse_schedule.push.validate_subscription", return_value=subscription) as validate:
            response = self.client.post("/api/me/push-subscriptions", json={**subscription, "expirationTime": None}, headers=self.headers)
        validate.assert_called_once_with(subscription)
        self.assertEqual(response.status_code, 201)
        self.assertEqual(self.store.add_subscription.call_args.args[:2], ("alice@example.test", subscription))
        self.store.set_settings.assert_not_called()
        with patch("hse_schedule.push.validate_subscription", side_effect=ValueError("sensitive data")):
            response = self.client.post("/api/me/push-subscriptions", json=subscription, headers=self.headers)
        self.assertEqual(response.status_code, 422)
        self.assertNotIn("sensitive", response.text)
        response = self.client.request("DELETE", "/api/me/push-subscriptions", json={"endpoint": subscription["endpoint"]}, headers=self.headers)
        self.assertEqual(response.status_code, 204)
        self.store.remove_subscription.assert_called_once_with("alice@example.test", subscription["endpoint"])

    def test_telegram_link_is_unique_short_lived_and_bound_to_identity(self):
        responses = [self.client.post("/api/me/telegram/link", headers=self.headers) for _ in range(2)]
        self.assertTrue(all(response.status_code == 200 for response in responses))
        first, second = (response.json() for response in responses)
        self.assertNotEqual(first["deep_link"], second["deep_link"])
        url = urlsplit(first["deep_link"])
        self.assertEqual((url.scheme, url.netloc, url.path), ("https", "t.me", "/UniversityScheduleBot"))
        token = parse_qs(url.query)["start"][0]
        self.assertGreaterEqual(len(token), 24)
        email, stored_token, expires = self.store.create_telegram_link.call_args_list[0].args
        self.assertEqual((email, stored_token), ("alice@example.test", token))
        self.assertLess(abs((expires - datetime.now(timezone.utc)).total_seconds() - 600), 5)
        self.assertEqual(self.client.get("/api/me/telegram", headers=self.headers).json(), {"linked": False, "username": None})
        self.assertEqual(self.client.delete("/api/me/telegram", headers=self.headers).status_code, 204)
        self.store.unlink_telegram.assert_called_once_with("alice@example.test")

    def test_telegram_provider_errors_do_not_expose_secrets(self):
        from hse_schedule.push import ChannelDeliveryError

        self.bot.get_username = Mock(side_effect=ChannelDeliveryError("secret bot token"))
        response = self.client.post("/api/me/telegram/link", headers=self.headers)
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("secret", response.text)
        self.store.create_telegram_link.assert_not_called()

    def test_unknown_student_cannot_create_preferences(self):
        self.app.dependency_overrides[self.app.state.account_dependency] = lambda: "unknown@example.test"
        response = self.client.patch("/api/me/notification-settings", json={"enabled": True})
        self.assertEqual(response.status_code, 404)
        self.store.set_settings.assert_not_called()

    def test_api_only_app_serves_no_pages(self):
        self.assertEqual(self.client.get("/").status_code, 404)
        self.assertEqual(self.client.get("/login").status_code, 404)
        self.assertEqual(self.client.get("/sw.js").status_code, 404)


class BellIntegrationTests(unittest.TestCase):
    def test_muted_inbox_and_read_state_are_private_through_api(self):
        from hse_schedule.notification_store import NotificationStore

        service = SimpleNamespace(directory=StudentDirectory([
            Student("alice@example.test", "Алиса", group_oids=("1000",)),
            Student("bob@example.test", "Борис", group_oids=("1001",)),
        ]))
        store = NotificationStore(":memory:")
        self.addCleanup(store.close)
        now = datetime.now(timezone.utc)
        for email in ("alice@example.test", "bob@example.test"):
            store.publish_notifications(email, [{
                "kind": "reminder", "title": "Скоро пара", "body": email,
                "payload": {}, "event_key": "same-key-per-account", "expires_at": None,
            }], now)
        app = create_app(service, {"alice": "alice@example.test", "bob": "bob@example.test"})
        register_notification_routes(app, service, store, app.state.account_dependency)
        with TestClient(app) as client:
            headers = {"Authorization": "Bearer alice"}
            inbox = client.get("/api/me/notifications", headers=headers).json()
            self.assertEqual(inbox["unread_count"], 1)
            self.assertEqual(inbox["items"][0]["body"], "alice@example.test")
            identifier = inbox["items"][0]["id"]
            other = client.post(f"/api/me/notifications/{identifier}/read", headers={"Authorization": "Bearer bob"})
            self.assertEqual(other.status_code, 404)
            self.assertEqual(client.post(f"/api/me/notifications/{identifier}/read", headers=headers).status_code, 200)
            self.assertEqual(client.get("/api/me/notifications", headers=headers).json()["unread_count"], 0)
            self.assertEqual(client.get("/api/me/notification-settings", headers=headers).json(), {"enabled": False})
        self.assertEqual(store.claim_deliveries(now), [])


if __name__ == "__main__":
    unittest.main()
