"""
KenBot OS — Facts Store
Stores/retrieves personal facts about Kenneth with visibility metadata.
Replaces the KV-based fun_facts approach with richer structure.
"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Literal, Optional

from memory.store import memory
from utils.logger import logger

Visibility = Literal[
    "private_self",
    "inner_circle_only",
    "friends_only",
    "family_safe",
    "public_safe",
    "global_content",
]

Confidence = Literal["high", "medium", "low"]

# Maximum facts kept per chat_id (rolling window)
_MAX_FACTS_PER_CHAT = 30
# Global Kenneth facts (cross-platform, public-safe only)
_GLOBAL_KEY = "facts:global"


class FactsStore:

    # ── Write ──────────────────────────────────────────────────────────────

    def add(
        self,
        fact_text: str,
        *,
        source_user: str = "unknown",
        chat_id: str = "",
        visibility: Visibility = "friends_only",
        confidence: Confidence = "medium",
    ) -> dict:
        """
        Store a fact. If chat_id given, scoped to that chat (won't leak
        to other chats). If visibility is public_safe / global_content,
        also added to the global pool for content generation.
        """
        entry = {
            "fact_text":   fact_text,
            "source_user": source_user,
            "visibility":  visibility,
            "confidence":  confidence,
            "timestamp":   datetime.utcnow().isoformat(),
            "chat_id":     chat_id,
        }

        # Per-chat store
        if chat_id:
            key = f"facts:{chat_id}"
            existing = self._load(key)
            existing.append(entry)
            existing = existing[-_MAX_FACTS_PER_CHAT:]
            self._save(key, existing)

        # Global pool for public-safe facts
        if visibility in ("public_safe", "global_content"):
            global_facts = self._load(_GLOBAL_KEY)
            global_facts.append(entry)
            global_facts = global_facts[-100:]
            self._save(_GLOBAL_KEY, global_facts)

        logger.debug(f"Fact stored [{visibility}]: {fact_text[:60]}")
        return entry

    # ── Read ───────────────────────────────────────────────────────────────

    def get_for_chat(
        self,
        chat_id: str,
        *,
        limit: int = 10,
        min_visibility: Optional[Visibility] = None,
    ) -> list[dict]:
        """
        Return the most recent facts scoped to this chat.
        Optionally filter by minimum visibility rank.
        """
        facts = self._load(f"facts:{chat_id}")
        if min_visibility:
            rank = _VIS_RANK.get(min_visibility, 0)
            facts = [f for f in facts if _VIS_RANK.get(f.get("visibility", "private_self"), 0) >= rank]
        return facts[-limit:]

    def get_global(self, limit: int = 20) -> list[dict]:
        """Return public-safe global facts (safe for injection into content)."""
        return self._load(_GLOBAL_KEY)[-limit:]

    def get_prompt_block(self, chat_id: str, *, limit: int = 8) -> str:
        """
        Returns a formatted block for injection into AI system prompts.
        Only includes facts visible at friends_only or above.
        """
        facts = self.get_for_chat(chat_id, limit=limit, min_visibility="friends_only")
        if not facts:
            return ""
        lines = [f"  - [{f['source_user']}]: {f['fact_text']}" for f in facts]
        return "FUN FACTS shared in this chat (use naturally, never share to other chats):\n" + "\n".join(lines)

    # ── Internal ───────────────────────────────────────────────────────────

    def _load(self, key: str) -> list:
        try:
            return json.loads(memory.get(key, "[]"))
        except Exception:
            return []

    def _save(self, key: str, data: list) -> None:
        memory.set(key, json.dumps(data))


# Visibility rank for filtering (higher = more public)
_VIS_RANK: dict[str, int] = {
    "private_self":      1,
    "inner_circle_only": 2,
    "friends_only":      3,
    "family_safe":       4,
    "public_safe":       5,
    "global_content":    6,
}

facts_store = FactsStore()
