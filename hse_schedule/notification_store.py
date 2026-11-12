"""Durable inbox, delivery outbox and channel bindings for personal accounts."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
from pathlib import Path


def _stamp(value: datetime | str) -> str:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Notification timestamps must include a timezone.")
    return value.astimezone(timezone.utc).isoformat()


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class NotificationStore:
    """A SQLite transaction commits observations, inbox events and fanout together.

    Email addresses passed here come from the application's trusted directory.
    Settings default to muted; enabling a channel never replays old inbox events.
    """

    def __init__(self, path: str | Path) -> None:
        path = str(path)
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(path, timeout=30, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.executescript("""
            CREATE TABLE IF NOT EXISTS notification_settings (
                email TEXT PRIMARY KEY, enabled INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY, email TEXT NOT NULL, event_key TEXT NOT NULL,
                kind TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
                payload TEXT NOT NULL, created_at TEXT NOT NULL, read_at TEXT,
                expires_at TEXT, UNIQUE(email, event_key)
            );
            CREATE INDEX IF NOT EXISTS inbox_owner ON notifications(email, id DESC);
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                endpoint TEXT PRIMARY KEY, email TEXT NOT NULL,
                subscription TEXT NOT NULL, created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS telegram_bindings (
                email TEXT PRIMARY KEY, chat_id TEXT NOT NULL UNIQUE, username TEXT
            );
            CREATE TABLE IF NOT EXISTS telegram_links (
                digest TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, expires_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notification_snapshots (
                email TEXT PRIMARY KEY, version INTEGER NOT NULL,
                start TEXT NOT NULL, finish TEXT NOT NULL, lessons TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS notification_deliveries (
                id INTEGER PRIMARY KEY, notification_id INTEGER NOT NULL
                    REFERENCES notifications(id), email TEXT NOT NULL,
                channel TEXT NOT NULL, target_key TEXT NOT NULL, target TEXT NOT NULL,
                state TEXT NOT NULL DEFAULT 'pending', attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT NOT NULL, lease_until TEXT, completed_at TEXT,
                UNIQUE(notification_id, channel, target_key)
            );
            CREATE INDEX IF NOT EXISTS delivery_due
                ON notification_deliveries(state, next_attempt_at, lease_until);
        """)
        self._db.commit()
        if path != ":memory:":
            Path(path).chmod(0o600)

    def close(self) -> None:
        with self._lock:
            self._db.close()

    @contextmanager
    def _transaction(self):
        with self._lock:
            self._db.execute("BEGIN IMMEDIATE")
            try:
                yield self._db
            except BaseException:
                self._db.rollback()
                raise
            else:
                self._db.commit()

    @staticmethod
    def _notification(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"], "kind": row["kind"], "title": row["title"],
            "body": row["body"], "payload": json.loads(row["payload"]),
            "created_at": row["created_at"], "read_at": row["read_at"],
        }

    def get_settings(self, email: str) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT enabled FROM notification_settings WHERE email=?", (email,)
            ).fetchone()
            return {"enabled": bool(row and row["enabled"])}

    def set_settings(self, email: str, enabled: bool) -> dict:
        if not isinstance(enabled, bool):
            raise ValueError("enabled must be a boolean.")
        with self._transaction() as db:
            db.execute(
                "INSERT INTO notification_settings VALUES (?, ?) "
                "ON CONFLICT(email) DO UPDATE SET enabled=excluded.enabled",
                (email, int(enabled)),
            )
            if not enabled:
                db.execute(
                    "UPDATE notification_deliveries SET state='cancelled' "
                    "WHERE email=? AND state IN ('pending', 'sending')", (email,)
                )
        return {"enabled": enabled}

    def list_notifications(
        self, email: str, *, limit: int = 50, before: int | None = None,
        unread_only: bool = False,
    ) -> dict:
        if not 1 <= limit <= 100:
            raise ValueError("limit must be between 1 and 100.")
        clauses, params = ["email=?"], [email]
        if before is not None:
            clauses.append("id<?")
            params.append(before)
        if unread_only:
            clauses.append("read_at IS NULL")
        with self._lock:
            rows = self._db.execute(
                "SELECT * FROM notifications WHERE " + " AND ".join(clauses)
                + " ORDER BY id DESC LIMIT ?", [*params, limit + 1]
            ).fetchall()
            count = self._db.execute(
                "SELECT COUNT(*) FROM notifications WHERE email=? AND read_at IS NULL", (email,)
            ).fetchone()[0]
        items = [self._notification(row) for row in rows[:limit]]
        return {
            "items": items, "unread_count": count,
            "next_before": items[-1]["id"] if len(rows) > limit else None,
        }

    def mark_read(self, email: str, notification_id: int, now: datetime) -> bool:
        with self._transaction() as db:
            result = db.execute(
                "UPDATE notifications SET read_at=COALESCE(read_at, ?) WHERE id=? AND email=?",
                (_stamp(now), notification_id, email),
            )
            return result.rowcount == 1

    def get_notification(self, email: str, notification_id: int) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM notifications WHERE email=? AND id=?", (email, notification_id)
            ).fetchone()
        return self._notification(row) if row is not None else None

    def mark_all_read(self, email: str, now: datetime) -> int:
        with self._transaction() as db:
            return db.execute(
                "UPDATE notifications SET read_at=? WHERE email=? AND read_at IS NULL",
                (_stamp(now), email),
            ).rowcount

    def add_subscription(self, email: str, subscription: dict, now: datetime) -> None:
        endpoint = subscription["endpoint"]
        with self._transaction() as db:
            db.execute(
                "UPDATE notification_deliveries SET state='cancelled' WHERE channel='webpush' "
                "AND target_key=? AND email<>? AND state IN ('pending', 'sending')",
                (endpoint, email),
            )
            db.execute(
                "INSERT INTO push_subscriptions VALUES (?, ?, ?, ?) "
                "ON CONFLICT(endpoint) DO UPDATE SET email=excluded.email, "
                "subscription=excluded.subscription, created_at=excluded.created_at",
                (endpoint, email, _json(subscription), _stamp(now)),
            )

    def remove_subscription(self, email: str, endpoint: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM push_subscriptions WHERE email=? AND endpoint=?", (email, endpoint))
            db.execute(
                "UPDATE notification_deliveries SET state='cancelled' WHERE email=? "
                "AND channel='webpush' AND target_key=? AND state IN ('pending', 'sending')",
                (email, endpoint),
            )

    def list_subscriptions(self, email: str) -> list[dict]:
        with self._lock:
            rows = self._db.execute(
                "SELECT subscription FROM push_subscriptions WHERE email=? ORDER BY endpoint", (email,)
            ).fetchall()
        return [json.loads(row[0]) for row in rows]

    def telegram_status(self, email: str) -> dict:
        with self._lock:
            row = self._db.execute(
                "SELECT username FROM telegram_bindings WHERE email=?", (email,)
            ).fetchone()
        return {"linked": row is not None, "username": row["username"] if row else None}

    def create_telegram_link(self, email: str, token: str, expires: datetime) -> None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        with self._transaction() as db:
            db.execute("DELETE FROM telegram_links WHERE email=?", (email,))
            db.execute("INSERT INTO telegram_links VALUES (?, ?, ?)", (digest, email, _stamp(expires)))

    def consume_telegram_link(
        self, token: str, chat_id: str, username: str | None, now: datetime,
    ) -> str | None:
        digest = hashlib.sha256(token.encode()).hexdigest()
        chat_id = str(chat_id)
        with self._transaction() as db:
            row = db.execute("SELECT * FROM telegram_links WHERE digest=?", (digest,)).fetchone()
            if row is None:
                return None
            db.execute("DELETE FROM telegram_links WHERE digest=?", (digest,))
            if row["expires_at"] <= _stamp(now):
                return None
            email = row["email"]
            db.execute(
                "UPDATE notification_deliveries SET state='cancelled' WHERE channel='telegram' "
                "AND (email=? OR target_key=?) AND state IN ('pending', 'sending')", (email, chat_id)
            )
            db.execute("DELETE FROM telegram_bindings WHERE email=? OR chat_id=?", (email, chat_id))
            db.execute("INSERT INTO telegram_bindings VALUES (?, ?, ?)", (email, chat_id, username))
            return email

    def unlink_telegram(self, email: str) -> None:
        with self._transaction() as db:
            db.execute("DELETE FROM telegram_links WHERE email=?", (email,))
            db.execute("DELETE FROM telegram_bindings WHERE email=?", (email,))
            db.execute(
                "UPDATE notification_deliveries SET state='cancelled' WHERE email=? "
                "AND channel='telegram' AND state IN ('pending', 'sending')", (email,)
            )

    def unlink_telegram_target(self, email: str, chat_id: str) -> None:
        """Remove a failed target without undoing a newer account binding."""
        chat_id = str(chat_id)
        with self._transaction() as db:
            db.execute(
                "DELETE FROM telegram_bindings WHERE email=? AND chat_id=?", (email, chat_id)
            )
            db.execute(
                "UPDATE notification_deliveries SET state='cancelled' WHERE email=? "
                "AND channel='telegram' AND target_key=? AND state IN ('pending','sending')",
                (email, chat_id),
            )

    def load_snapshot(self, email: str) -> dict | None:
        with self._lock:
            row = self._db.execute(
                "SELECT * FROM notification_snapshots WHERE email=?", (email,)
            ).fetchone()
        if row is None:
            return None
        return {"version": row["version"], "start": row["start"], "finish": row["finish"],
                "lessons": json.loads(row["lessons"])}

    def commit_observation(
        self, email: str, expected_version: int | None, *, start: date, finish: date,
        lessons: list[dict], notifications: list[dict], now: datetime,
    ) -> bool:
        timestamp = _stamp(now)
        with self._transaction() as db:
            row = db.execute("SELECT version FROM notification_snapshots WHERE email=?", (email,)).fetchone()
            if (row[0] if row else None) != expected_version:
                return False
            db.execute(
                "INSERT INTO notification_snapshots VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(email) DO UPDATE SET version=excluded.version, start=excluded.start, "
                "finish=excluded.finish, lessons=excluded.lessons",
                (email, (expected_version or 0) + 1, start.isoformat(), finish.isoformat(), _json(lessons)),
            )
            self._publish(db, email, notifications, timestamp)
        return True

    def publish_notifications(
        self, email: str, notifications: list[dict], now: datetime, *,
        expected_version: int | None = None,
    ) -> bool:
        with self._transaction() as db:
            if expected_version is not None:
                row = db.execute(
                    "SELECT version FROM notification_snapshots WHERE email=?", (email,)
                ).fetchone()
                if row is None or row[0] != expected_version:
                    return False
            self._publish(db, email, notifications, _stamp(now))
        return True

    def update_reminder_details(
        self, email: str, drafts: list[dict], *, expected_version: int,
    ) -> bool:
        """Refresh an existing reminder without replaying it or adding targets."""
        with self._transaction() as db:
            snapshot = db.execute(
                "SELECT version FROM notification_snapshots WHERE email=?", (email,)
            ).fetchone()
            if snapshot is None or snapshot[0] != expected_version:
                return False
            for draft in drafts:
                expiry = _stamp(draft["expires_at"]) if draft.get("expires_at") else None
                db.execute(
                    "UPDATE notifications SET title=?,body=?,payload=?,expires_at=? "
                    "WHERE email=? AND event_key=? AND kind='reminder'",
                    (draft["title"], draft["body"], _json(draft["payload"]), expiry,
                     email, draft["event_key"]),
                )
        return True

    def _publish(self, db: sqlite3.Connection, email: str, notifications: list[dict], timestamp: str) -> None:
        enabled = db.execute(
            "SELECT enabled FROM notification_settings WHERE email=?", (email,)
        ).fetchone()
        for draft in notifications:
            expiry = _stamp(draft["expires_at"]) if draft.get("expires_at") else None
            cursor = db.execute(
                "INSERT OR IGNORE INTO notifications "
                "(email,event_key,kind,title,body,payload,created_at,expires_at) VALUES (?,?,?,?,?,?,?,?)",
                (email, draft["event_key"], draft["kind"], draft["title"], draft["body"],
                 _json(draft["payload"]), timestamp, expiry),
            )
            if not cursor.rowcount or not enabled or not enabled[0] or (expiry and expiry <= timestamp):
                continue
            notification_id = cursor.lastrowid
            targets = [
                ("webpush", target["endpoint"], json.loads(target["subscription"]))
                for target in db.execute("SELECT * FROM push_subscriptions WHERE email=?", (email,))
            ]
            telegram = db.execute("SELECT chat_id FROM telegram_bindings WHERE email=?", (email,)).fetchone()
            if telegram:
                targets.append(("telegram", telegram[0], {"chat_id": telegram[0]}))
            for channel, target_key, target in targets:
                db.execute(
                    "INSERT INTO notification_deliveries "
                    "(notification_id,email,channel,target_key,target,next_attempt_at) VALUES (?,?,?,?,?,?)",
                    (notification_id, email, channel, target_key, _json(target), timestamp),
                )

    def claim_deliveries(self, now: datetime, *, limit: int = 50, lease_seconds: int = 60) -> list[dict]:
        timestamp = _stamp(now)
        lease_until = _stamp(now + timedelta(seconds=lease_seconds))
        deliveries = []
        with self._transaction() as db:
            rows = db.execute(
                "SELECT d.*, n.expires_at FROM notification_deliveries d "
                "JOIN notifications n ON n.id=d.notification_id WHERE "
                "(d.state='pending' AND d.next_attempt_at<=?) OR "
                "(d.state='sending' AND d.lease_until<=?) ORDER BY d.id LIMIT ?",
                (timestamp, timestamp, limit),
            ).fetchall()
            for row in rows:
                settings = db.execute("SELECT enabled FROM notification_settings WHERE email=?", (row["email"],)).fetchone()
                if row["channel"] == "webpush":
                    target = db.execute(
                        "SELECT subscription FROM push_subscriptions WHERE email=? AND endpoint=?",
                        (row["email"], row["target_key"]),
                    ).fetchone()
                    target_data = json.loads(target[0]) if target else None
                else:
                    target = db.execute(
                        "SELECT chat_id FROM telegram_bindings WHERE email=? AND chat_id=?",
                        (row["email"], row["target_key"]),
                    ).fetchone()
                    target_data = {"chat_id": target[0]} if target else None
                if not settings or not settings[0] or target_data is None or (row["expires_at"] and row["expires_at"] <= timestamp):
                    db.execute("UPDATE notification_deliveries SET state='cancelled' WHERE id=?", (row["id"],))
                    continue
                if row["attempts"] >= 5:
                    db.execute("UPDATE notification_deliveries SET state='failed' WHERE id=?", (row["id"],))
                    continue
                db.execute(
                    "UPDATE notification_deliveries SET state='sending', attempts=attempts+1, "
                    "lease_until=?, target=? WHERE id=?", (lease_until, _json(target_data), row["id"]),
                )
                notification = db.execute("SELECT * FROM notifications WHERE id=?", (row["notification_id"],)).fetchone()
                deliveries.append({
                    "id": row["id"], "email": row["email"], "channel": row["channel"],
                    "target": target_data, "notification": self._notification(notification),
                    "attempts": row["attempts"] + 1,
                })
        return deliveries

    def delivery_is_active(self, delivery_id: int, now: datetime) -> bool:
        """Recheck a claimed delivery after account/channel settings may change."""
        timestamp = _stamp(now)
        with self._lock:
            row = self._db.execute(
                "SELECT d.*,n.expires_at FROM notification_deliveries d "
                "JOIN notifications n ON n.id=d.notification_id WHERE d.id=? "
                "AND d.state='sending' AND d.lease_until>?", (delivery_id, timestamp),
            ).fetchone()
            if row is None or (row["expires_at"] and row["expires_at"] <= timestamp):
                return False
            settings = self._db.execute(
                "SELECT enabled FROM notification_settings WHERE email=?", (row["email"],)
            ).fetchone()
            if not settings or not settings[0]:
                return False
            if row["channel"] == "webpush":
                target = self._db.execute(
                    "SELECT 1 FROM push_subscriptions WHERE email=? AND endpoint=?",
                    (row["email"], row["target_key"]),
                ).fetchone()
            else:
                target = self._db.execute(
                    "SELECT 1 FROM telegram_bindings WHERE email=? AND chat_id=?",
                    (row["email"], row["target_key"]),
                ).fetchone()
            return target is not None

    def complete_delivery(self, delivery_id: int, now: datetime) -> None:
        with self._transaction() as db:
            db.execute(
                "UPDATE notification_deliveries SET state='sent', completed_at=?, lease_until=NULL "
                "WHERE id=? AND state='sending'", (_stamp(now), delivery_id),
            )

    def retry_delivery(self, delivery_id: int, now: datetime, *, permanent: bool = False) -> None:
        with self._transaction() as db:
            row = db.execute("SELECT attempts FROM notification_deliveries WHERE id=? AND state='sending'", (delivery_id,)).fetchone()
            if row is None:
                return
            failed = permanent or row[0] >= 5
            delay = min(30 * (2 ** max(0, row[0] - 1)), 600)
            db.execute(
                "UPDATE notification_deliveries SET state=?, next_attempt_at=?, lease_until=NULL WHERE id=?",
                ("failed" if failed else "pending", _stamp(now + timedelta(seconds=delay)), delivery_id),
            )

    def cancel_stale_reminders(
        self, email: str, active_event_keys: set[str], *, expected_version: int | None = None,
    ) -> None:
        with self._transaction() as db:
            if expected_version is not None:
                snapshot = db.execute(
                    "SELECT version FROM notification_snapshots WHERE email=?", (email,)
                ).fetchone()
                if snapshot is None or snapshot[0] != expected_version:
                    return
            rows = db.execute(
                "SELECT d.id,n.event_key FROM notification_deliveries d "
                "JOIN notifications n ON n.id=d.notification_id WHERE d.email=? "
                "AND n.kind='reminder' AND d.state IN ('pending','sending')", (email,),
            ).fetchall()
            for row in rows:
                if row["event_key"] not in active_event_keys:
                    db.execute("UPDATE notification_deliveries SET state='cancelled' WHERE id=?", (row["id"],))
