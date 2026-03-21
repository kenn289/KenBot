from __future__ import annotations

import json
import re
import time
from typing import Optional

from memory.store import memory

_TOPIC_LEDGER_KEY = "cross_platform_topic_ledger"
_LEDGER_MAX = 220


class CrossPlatformBrain:
    """
    Lightweight shared signal layer used by X, Reddit and YouTube paths.
    - Keeps a global recent-topic ledger (anti-repeat across platforms)
    - Builds one unified context block from live + learned signals
    - Sanitizes final social text to avoid prompt/meta leakage
    """

    @staticmethod
    def sanitize_social_text(text: str, max_chars: int = 320) -> str:
        raw = (text or "").strip().strip('"\'')
        if not raw:
            return ""

        if raw.startswith("```"):
            raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()

        bad_line = re.compile(
            r"(?i)^("
            r"reply\s*[:\-]?|"
            r"best\s*reply.*:|"
            r"write\s*(your\s*)?(reply|tweet|comment)\s*[:\-]?|"
            r"original\s*(tweet|post)\s*[:\-]?|"
            r"reddit\s*post\s*title\s*[:\-]?|"
            r"tweet\s*(idea|option)?\s*\d*\s*[:\-]?|"
            r"option\s*\d+\s*[:\-]?|"
            r"caption\s*[:\-]?|"
            r"here'?s\s*(a|one)\s*(tweet|reply|comment)"
            r")"
        )

        lines = [line.strip() for line in raw.splitlines() if line.strip()]
        kept = [line for line in lines if not bad_line.search(line)]
        if kept:
            raw = "\n".join(kept)

        raw = re.split(r"(?i)\bor if you want\b", raw)[0]
        raw = re.split(r"(?i)\bif you want (a )?(spicier|safer|alt)\b", raw)[0]
        raw = re.split(r"(?i)\balternative\s*[:\-]?", raw)[0]
        raw = re.sub(r"\n{3,}", "\n\n", raw)
        raw = re.sub(r"[ \t]{2,}", " ", raw).strip()
        return raw[:max_chars]

    @staticmethod
    def _norm_topic(text: str) -> str:
        normalized = (text or "").lower().strip()
        normalized = re.sub(r"[^a-z0-9\s]", " ", normalized)
        normalized = re.sub(r"\s+", " ", normalized).strip()
        return normalized[:180]

    @staticmethod
    def _tokens(text: str) -> set[str]:
        return {token for token in CrossPlatformBrain._norm_topic(text).split() if len(token) > 2}

    @staticmethod
    def _load_ledger() -> list[dict]:
        try:
            raw = memory.get(_TOPIC_LEDGER_KEY, "[]")
            loaded = json.loads(raw)
            return loaded if isinstance(loaded, list) else []
        except Exception:
            return []

    @staticmethod
    def _save_ledger(entries: list[dict]) -> None:
        memory.set(_TOPIC_LEDGER_KEY, json.dumps(entries[-_LEDGER_MAX:]))

    def record_topic(self, platform: str, topic: str, source: str = "") -> None:
        cleaned = self._norm_topic(topic)
        if not cleaned:
            return
        entries = self._load_ledger()
        entries.append({
            "platform": (platform or "general").strip().lower()[:20],
            "topic": topic[:220],
            "normalized": cleaned,
            "source": source[:120],
            "ts": int(time.time()),
        })
        self._save_ledger(entries)

    def recent_topics(self, limit: int = 18, platform: Optional[str] = None) -> list[str]:
        rows = self._load_ledger()
        if platform:
            platform = platform.lower().strip()
            rows = [row for row in rows if row.get("platform") == platform]
        return [str(row.get("topic", "")) for row in rows[-limit:] if row.get("topic")]

    def is_topic_recent(self, topic: str, lookback: int = 30) -> bool:
        now_norm = self._norm_topic(topic)
        if not now_norm:
            return False
        now_tokens = self._tokens(now_norm)

        for row in reversed(self._load_ledger()[-lookback:]):
            old_norm = str(row.get("normalized") or self._norm_topic(str(row.get("topic", ""))))
            if not old_norm:
                continue
            if now_norm == old_norm or now_norm in old_norm or old_norm in now_norm:
                return True
            overlap = len(now_tokens & self._tokens(old_norm))
            if overlap >= 3:
                return True
        return False

    def build_unified_context(self, seed_topic: str = "", platform: str = "general") -> str:
        """
        Unified signal block consumed by all generation paths.
        Uses low-cost, best-effort sources and degrades gracefully.
        """
        blocks: list[str] = []

        x_feed_topics: list[str] = []
        try:
            raw_feed = memory.get("x_learned_feed_topics", "[]")
            parsed_feed = json.loads(raw_feed) if raw_feed else []
            if isinstance(parsed_feed, list):
                x_feed_topics = [str(item) for item in parsed_feed if item][:8]
        except Exception:
            pass
        if x_feed_topics:
            blocks.append("X FEED SIGNALS:\n" + "\n".join(f"  • {item}" for item in x_feed_topics))

        trend_topics: list[str] = []
        try:
            from content.trend_scanner import trend_scanner

            for trend in trend_scanner.get_trends(force_refresh=False)[:10]:
                topic = str(trend.get("topic", "")).strip()
                if topic:
                    trend_topics.append(topic)
        except Exception:
            pass
        if trend_topics:
            blocks.append("PUBLIC TREND SIGNALS (REDDIT + CONTEXT):\n" + "\n".join(f"  • {item}" for item in trend_topics[:8]))

        soul_topics: list[str] = []
        try:
            from core.soul_engine import soul as _soul

            soul_topics = [str(item) for item in _soul.get_dynamic_topics()[:10] if item]
        except Exception:
            pass
        if soul_topics:
            blocks.append("SOUL/INTEREST SIGNALS:\n" + "\n".join(f"  • {item}" for item in soul_topics[:8]))

        recent = self.recent_topics(limit=10)
        if recent:
            blocks.append(
                "RECENTLY POSTED/COMMENTED (AVOID REPEATING SAME ANGLE):\n"
                + "\n".join(f"  • {item}" for item in recent)
            )

        if seed_topic and self.is_topic_recent(seed_topic, lookback=35):
            blocks.append(
                f"FRESHNESS ALERT: '{seed_topic}' is close to recently used topics. "
                "Choose a different angle/topic unless there is genuinely new context."
            )

        if not blocks:
            return ""

        return (
            f"═══ CROSS-PLATFORM CONTEXT ({platform}) ═══\n"
            + "\n\n".join(blocks)
            + "\n\nUse this to stay current and avoid repeated stale takes."
        )


cross_platform_brain = CrossPlatformBrain()
