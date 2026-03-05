"""
Ken ClawdBot — Mood State Manager
Ken is moody. This module tracks and transitions his current mood.
Mood is persistent (SQLite), changes over time & based on context.
"""
from __future__ import annotations

import random
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config.ken_personality import MOODS, MOOD_TRIGGERS
from config.settings import settings
from utils.logger import logger

DB_PATH = settings.root_dir / "memory" / "ken_state.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)


class MoodManager:
    """
    Persists Ken's current mood in SQLite.
    Mood auto-drifts every ~4 hours unless locked by a trigger.
    """

    def __init__(self) -> None:
        self._conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        self._init_db()

    # ── DB Setup ────────────────────────────────────────────
    def _init_db(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS mood_state (
                id       INTEGER PRIMARY KEY,
                mood     TEXT NOT NULL,
                reason   TEXT,
                locked   INTEGER DEFAULT 0,
                set_at   TEXT NOT NULL
            )
            """
        )
        self._conn.commit()
        # Ensure at least one row
        cursor = self._conn.execute("SELECT COUNT(*) FROM mood_state")
        if cursor.fetchone()[0] == 0:
            self._set("neutral", reason="cold start")

    # ── Internal setter ─────────────────────────────────────
    def _set(self, mood: str, reason: str = "", locked: bool = False) -> None:
        self._conn.execute("DELETE FROM mood_state")
        self._conn.execute(
            "INSERT INTO mood_state (mood, reason, locked, set_at) VALUES (?, ?, ?, ?)",
            (mood, reason, int(locked), datetime.utcnow().isoformat()),
        )
        self._conn.commit()
        logger.debug(f"Mood → {mood} | reason: {reason} | locked: {locked}")

    # ── Public API ──────────────────────────────────────────
    def current(self) -> str:
        """Return Ken's current mood string."""
        self._maybe_drift()
        row = self._conn.execute("SELECT mood FROM mood_state LIMIT 1").fetchone()
        return row[0] if row else "neutral"

    def current_profile(self) -> dict:
        """Return full mood dict with description & tone_modifier."""
        mood = self.current()
        return {"name": mood, **MOODS.get(mood, MOODS["neutral"])}

    def detect_from_text(self, text: str) -> Optional[str]:
        """Scan text for mood-trigger keywords; return triggered mood or None."""
        lower = text.lower()
        for mood, keywords in MOOD_TRIGGERS.items():
            if any(kw in lower for kw in keywords):
                return mood
        return None

    def apply_context(self, text: str) -> str:
        """Check if incoming text should temporarily shift mood."""
        triggered = self.detect_from_text(text)
        if triggered:
            row = self._conn.execute(
                "SELECT locked FROM mood_state LIMIT 1"
            ).fetchone()
            is_locked = row and row[0] == 1
            if not is_locked:
                self._set(triggered, reason=f"triggered by message context", locked=False)
            return triggered or self.current()
        return self.current()

    def force_mood(self, mood: str, lock_minutes: int = 60) -> None:
        """Manually override mood (e.g., from a WhatsApp command)."""
        if mood not in MOODS:
            logger.warning(f"Unknown mood: {mood}")
            return
        self._set(mood, reason="manual override", locked=True)
        logger.info(f"Mood force-set to '{mood}' for {lock_minutes} minutes")

    # ── Drift logic ─────────────────────────────────────────
    def _maybe_drift(self) -> None:
        """
        If mood hasn't changed in > 4 hours (and isn't hard-locked),
        drift to a new mood weighted by MOODS[mood]["weight"].
        """
        row = self._conn.execute(
            "SELECT mood, locked, set_at FROM mood_state LIMIT 1"
        ).fetchone()
        if not row:
            return

        mood, locked, set_at_str = row
        if locked:
            return

        set_at = datetime.fromisoformat(set_at_str)
        if datetime.utcnow() - set_at > timedelta(hours=4):
            new_mood = random.choices(
                population=list(MOODS.keys()),
                weights=[v["weight"] for v in MOODS.values()],
                k=1,
            )[0]
            self._set(new_mood, reason="natural drift")


# Singleton
mood_manager = MoodManager()
