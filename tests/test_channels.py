import base64
import json
import logging
import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from pywebpush import WebPushException

from hse_schedule.errors import ConfigurationError
from hse_schedule.push import ChannelDeliveryError, WebPushSender, validate_subscription
from hse_schedule.telegram import TelegramBot


def encoded(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def subscription(endpoint="https://fcm.googleapis.com/fcm/send/browser-id"):
    key = ec.generate_private_key(ec.SECP256R1()).public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return {"endpoint": endpoint, "keys": {"p256dh": encoded(key), "auth": encoded(os.urandom(16))}}


NOTIFICATION = {"id": 1, "title": "Пара через 10 минут", "body": "Математика, аудитория 101"}


class WebPushTests(unittest.TestCase):
    def test_key_is_persistent_private_and_accepted_by_webpush(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state" / "vapid.pem"
            sender = WebPushSender(path)
            again = WebPushSender(path)
            self.assertEqual(sender.public_key, again.public_key)
            self.assertEqual(len(base64.urlsafe_b64decode(sender.public_key + "=")), 65)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            response = requests.Response()
            response.status_code = 201
            with patch("requests.sessions.Session.request", return_value=response) as request:
                sender.send(subscription(), NOTIFICATION)
            self.assertEqual(request.call_count, 1)
            self.assertIn("vapid", request.call_args.kwargs["headers"]["authorization"].lower())

    def test_subscription_rejects_non_push_endpoints_and_bad_keys(self):
        for endpoint in (
            "http://fcm.googleapis.com/push", "https://127.0.0.1/push",
            "https://fcm.googleapis.com.evil.test/push", "https://push.internal/push",
            "https://name@fcm.googleapis.com/push", "https://fcm.googleapis.com:444/push",
            "https://fcm.googleapis.com/push#fragment",
        ):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validate_subscription(subscription(endpoint))
        for keys in ({}, {"p256dh": "bad", "auth": "bad"}, {"p256dh": encoded(b"\x04" * 65), "auth": encoded(b"a" * 16)}):
            with self.subTest(keys=keys), self.assertRaises(ValueError):
                validate_subscription({"endpoint": "https://fcm.googleapis.com/push", "keys": keys})

    def test_supported_push_services_and_removed_extra_fields(self):
        for endpoint in (
            "https://updates.push.services.mozilla.com/wpush/v2/id",
            "https://web.push.apple.com/id", "https://wns2-example.notify.windows.com/w/?token=id",
        ):
            value = subscription(endpoint)
            result = validate_subscription({**value, "expirationTime": None, "private": "not stored"})
            self.assertEqual(result, value)

    def test_delivery_payload_is_safe_and_provider_failure_is_classified(self):
        with tempfile.TemporaryDirectory() as directory:
            sender = WebPushSender(Path(directory) / "vapid.pem")
            with patch("pywebpush.webpush") as send:
                sender.send(subscription(), {**NOTIFICATION, "email": "not-in-push@example.test"})
            payload = json.loads(send.call_args.kwargs["data"])
            self.assertEqual(payload["tag"], "notification-1")
            self.assertNotIn("email", payload)
            self.assertEqual(send.call_args.kwargs["timeout"], 10)
            response = requests.Response()
            response.status_code = 410
            with patch("pywebpush.webpush", side_effect=WebPushException("private endpoint secret", response=response)):
                with self.assertRaises(ChannelDeliveryError) as caught:
                    sender.send(subscription(), NOTIFICATION)
            self.assertTrue(caught.exception.permanent)
            self.assertTrue(caught.exception.remove_target)
            self.assertNotIn("secret", str(caught.exception))

    def test_invalid_contact_is_configuration_error(self):
        with tempfile.TemporaryDirectory() as directory:
            for contact in ("invalid", "http://example.edu", "mailto:", "mailto:a@example.edu\n"):
                with self.subTest(contact=contact), self.assertRaises(ConfigurationError):
                    WebPushSender(Path(directory) / "vapid.pem", contact)

    def test_reminder_ttl_never_outlives_the_lesson_start(self):
        now = datetime(2026, 11, 12, 9, 20, tzinfo=timezone.utc)

        class FrozenDatetime(datetime):
            @classmethod
            def now(cls, tz=None):
                return now.astimezone(tz)

        with tempfile.TemporaryDirectory() as directory:
            sender = WebPushSender(Path(directory) / "vapid.pem")
            notification = {
                **NOTIFICATION, "kind": "reminder",
                "payload": {"lesson": {"starts_at": (now + timedelta(seconds=125)).isoformat()}},
            }
            with patch("hse_schedule.push.datetime", FrozenDatetime), patch("pywebpush.webpush") as send:
                sender.send(subscription(), notification)
            self.assertEqual(send.call_args.kwargs["ttl"], 125)
            for start in (now, now - timedelta(seconds=1)):
                notification["payload"]["lesson"]["starts_at"] = start.isoformat()
                with patch("hse_schedule.push.datetime", FrozenDatetime), patch("pywebpush.webpush") as send:
                    with self.assertRaises(ChannelDeliveryError) as caught:
                        sender.send(subscription(), notification)
                self.assertTrue(caught.exception.permanent)
                send.assert_not_called()


class TelegramTests(unittest.TestCase):
    token = "123:bot_secret"

    def bot(self, handler, **kwargs):
        return TelegramBot(self.token, transport=httpx.MockTransport(handler), **kwargs)

    def test_bot_username_is_verified_once_and_cached(self):
        requests_seen = []
        def handler(request):
            requests_seen.append(request)
            self.assertTrue(request.url.path.endswith("/getMe"))
            return httpx.Response(200, json={"ok": True, "result": {"username": "example_schedule_bot"}})
        bot = self.bot(handler)
        self.assertEqual(bot.get_username(), "example_schedule_bot")
        self.assertEqual(bot.get_username(), "example_schedule_bot")
        self.assertEqual(len(requests_seen), 1)

    def test_notification_is_plain_text_to_only_the_bound_private_chat(self):
        def handler(request):
            self.assertTrue(request.url.path.endswith("/sendMessage"))
            body = json.loads(request.content)
            self.assertEqual(body["chat_id"], "12345")
            self.assertEqual(body["text"], "Пара через 10 минут\n\nМатематика, аудитория 101")
            self.assertNotIn("parse_mode", body)
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        self.bot(handler).send({"chat_id": "12345"}, NOTIFICATION)

    def test_http_errors_are_sanitized_and_blocked_chats_removed(self):
        def blocked(_request):
            return httpx.Response(403, json={"ok": False, "error_code": 403, "description": "private secret"})
        with self.assertRaises(ChannelDeliveryError) as caught:
            self.bot(blocked).send({"chat_id": "12345"}, NOTIFICATION)
        self.assertTrue(caught.exception.permanent)
        self.assertTrue(caught.exception.remove_target)
        self.assertNotIn("secret", str(caught.exception))
        def timeout(request):
            raise httpx.ReadTimeout(f"secret {self.token}", request=request)
        with self.assertRaises(ChannelDeliveryError) as caught:
            self.bot(timeout).get_username()
        self.assertNotIn(self.token, str(caught.exception))
        self.assertFalse(caught.exception.permanent)

    def test_telegram_request_logging_redacts_bot_token(self):
        bot = self.bot(lambda _: httpx.Response(200, json={"ok": True, "result": {"username": "example_bot"}}))
        with self.assertLogs("httpx", level=logging.INFO) as captured:
            bot.get_username()
        self.assertNotIn(self.token, " ".join(captured.output))
        self.assertIn("[redacted]", " ".join(captured.output))

    def test_only_private_start_from_matching_user_consumes_one_time_token(self):
        token = "single_use_link_token_1234"
        updates = []
        def update(identifier, **overrides):
            message = {
                "chat": {"type": "private", "id": 12345},
                "from": {"id": 12345, "username": "example_user"},
                "text": f"/start {token}",
            }
            message.update(overrides)
            return {"update_id": identifier, "message": message}
        updates.extend((
            update(1, chat={"type": "group", "id": 12345}),
            update(2, **{"from": {"id": 555}}),
            update(3, text="example_user"), update(4),
        ))
        requests_seen = []
        def handler(request):
            body = json.loads(request.content)
            requests_seen.append((request.url.path.rsplit("/", 1)[-1], body))
            if request.url.path.endswith("/getUpdates"):
                return httpx.Response(200, json={"ok": True, "result": updates if body["offset"] == 0 else []})
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        store = Mock()
        store.consume_telegram_link.return_value = "student@example.test"
        now = datetime(2026, 11, 12, tzinfo=timezone.utc)
        bot = self.bot(handler)
        bot.poll_once(store, now)
        bot.poll_once(store, now)
        store.consume_telegram_link.assert_called_once_with(token, "12345", "example_user", now)
        self.assertEqual(requests_seen[-1][1]["offset"], 5)
        self.assertEqual([name for name, _ in requests_seen].count("sendMessage"), 1)

    def test_invalid_or_expired_link_does_not_send_confirmation(self):
        def handler(request):
            self.assertTrue(request.url.path.endswith("/getUpdates"))
            return httpx.Response(200, json={"ok": True, "result": [{"update_id": 1, "message": {
                "chat": {"type": "private", "id": 12345}, "from": {"id": 12345},
                "text": "/start expired_single_use_nonce_1234",
            }}]})
        store = Mock()
        store.consume_telegram_link.return_value = None
        self.bot(handler).poll_once(store, datetime.now(timezone.utc))
        self.assertEqual(store.consume_telegram_link.call_count, 1)


if __name__ == "__main__":
    unittest.main()
