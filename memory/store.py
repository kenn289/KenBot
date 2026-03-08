"""
Ken ClawdBot — Memory Store
SQLite-backed persistent memory.
Stores: conversations, posted content hashes (dedup), reminders, tasks.
"""
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config.settings import settings
from utils.logger import logger

DB_PATH = settings.root_dir / "memory" / "ken_memory.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class MemoryStore:
    def __init__(self) -> None:
        self._db = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._init_tables()

    def _init_tables(self) -> None:
        self._db.executescript(
            """
            -- Chat history per sender/group (last 20 msgs for context)
            CREATE TABLE IF NOT EXISTS chat_history (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                channel     TEXT NOT NULL,  -- 'whatsapp' | 'twitter_dm'
                chat_id     TEXT NOT NULL,  -- phone/group JID or twitter user_id
                role        TEXT NOT NULL,  -- 'user' | 'ken'
                message     TEXT NOT NULL,
                created_at  TEXT NOT NULL
            );

            -- Content dedup (avoid re-posting same stuff)
            CREATE TABLE IF NOT EXISTS posted_content (
                hash        TEXT PRIMARY KEY,
                platform    TEXT NOT NULL,  -- 'twitter' | 'youtube'
                content     TEXT,
                post_id     TEXT,
                posted_at   TEXT NOT NULL
            );

            -- Reminders queue
            CREATE TABLE IF NOT EXISTS reminders (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                task        TEXT NOT NULL,
                due_at      TEXT NOT NULL,
                sent        INTEGER DEFAULT 0,
                created_at  TEXT NOT NULL
            );

            -- General key-value store
            CREATE TABLE IF NOT EXISTS kv_store (
                key         TEXT PRIMARY KEY,
                value       TEXT,
                updated_at  TEXT
            );
            """
        )
        self._db.commit()

    # ── Chat History ──────────────────────────────────────
    def add_message(self, channel: str, chat_id: str, role: str, message: str) -> None:
        self._db.execute(
            "INSERT INTO chat_history (channel, chat_id, role, message, created_at) VALUES (?,?,?,?,?)",
            (channel, chat_id, role, message, datetime.utcnow().isoformat()),
        )
        self._db.commit()
        # Keep only last 40 rows per chat
        self._db.execute(
            """
            DELETE FROM chat_history WHERE id IN (
                SELECT id FROM chat_history
                WHERE channel=? AND chat_id=?
                ORDER BY id DESC
                LIMIT -1 OFFSET 40
            )
            """,
            (channel, chat_id),
        )
        self._db.commit()

    def get_context(self, channel: str, chat_id: str, last_n: int = 10) -> str:
        """Returns last N messages as a formatted string for AI context."""
        rows = self._db.execute(
            """
            SELECT role, message FROM chat_history
            WHERE channel=? AND chat_id=?
            ORDER BY id DESC LIMIT ?
            """,
            (channel, chat_id, last_n),
        ).fetchall()
        lines = [f"[{r['role']}]: {r['message']}" for r in reversed(rows)]
        return "\n".join(lines)

    # ── Content Dedup ─────────────────────────────────────
    def already_posted(self, content_hash: str) -> bool:
        row = self._db.execute(
            "SELECT 1 FROM posted_content WHERE hash=?", (content_hash,)
        ).fetchone()
        return row is not None

    def mark_posted(self, content_hash: str, platform: str, content: str, post_id: str = "") -> None:
        self._db.execute(
            "INSERT OR IGNORE INTO posted_content VALUES (?,?,?,?,?)",
            (content_hash, platform, content[:500], post_id, datetime.utcnow().isoformat()),
        )
        self._db.commit()

    # ── Reminders ─────────────────────────────────────────
    def add_reminder(self, task: str, due_at: datetime) -> int:
        cursor = self._db.execute(
            "INSERT INTO reminders (task, due_at, created_at) VALUES (?,?,?)",
            (task, due_at.isoformat(), datetime.utcnow().isoformat()),
        )
        self._db.commit()
        logger.info(f"Reminder added: '{task}' due {due_at}")
        return cursor.lastrowid  # type: ignore

    def pending_reminders(self) -> list[dict]:
        """Return all reminders due now or overdue that haven't been sent."""
        rows = self._db.execute(
            "SELECT * FROM reminders WHERE sent=0 AND due_at <= ?",
            (datetime.utcnow().isoformat(),),
        ).fetchall()
        return [dict(r) for r in rows]

    def mark_reminder_sent(self, reminder_id: int) -> None:
        self._db.execute("UPDATE reminders SET sent=1 WHERE id=?", (reminder_id,))
        self._db.commit()

    # ── KV Store ──────────────────────────────────────────
    def set(self, key: str, value: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO kv_store VALUES (?,?,?)",
            (key, value, datetime.utcnow().isoformat()),
        )
        self._db.commit()

    def get(self, key: str, default: str = "") -> str:
        row = self._db.execute("SELECT value FROM kv_store WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    # --- Contact type (friend / family / adult / colleague / unknown) ---
    def set_contact_type(self, contact_id: str, contact_type: str) -> None:
        self.set(f"contact_type:{contact_id}", contact_type.strip().lower())

    def get_contact_type(self, contact_id: str) -> str:
        return self.get(f"contact_type:{contact_id}", "unknown")

    # --- Fun facts (per-chat, never cross-contaminate) ---
    def store_fun_fact(self, chat_id: str, speaker: str, fact: str) -> None:
        import json
        key = f"fun_facts:{chat_id}"
        existing = json.loads(self.get(key, "[]"))
        existing.append({"speaker": speaker, "fact": fact})
        existing = existing[-20:]  # keep last 20 per chat
        self.set(key, json.dumps(existing))

    def get_fun_facts(self, chat_id: str) -> list:
        import json
        return json.loads(self.get(f"fun_facts:{chat_id}", "[]"))

    # --- Notification queue ---
    def queue_notification(self, message: str) -> None:
        """Queue a message to be sent to Kenneth via WhatsApp."""
        import threading
        if not hasattr(self, "_notif_lock"):
            self._notif_lock = threading.Lock()
            self._notif_queue: list = []
        with self._notif_lock:
            self._notif_queue.append(message)

    def pop_notifications(self) -> list:
        """Return and clear all pending notifications."""
        if not hasattr(self, "_notif_queue"):
            return []
        with self._notif_lock:
            msgs = list(self._notif_queue)
            self._notif_queue.clear()
        return msgs


# Singleton
memory = MemoryStore()
