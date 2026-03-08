"""
KenBot OS — Social Graph
Tracks relationship tiers, trust, topics, speech rules per contact.
All data stored in KV store (memory.set/get) — no new DB tables needed.
"""
from __future__ import annotations

import json
from datetime import datetime
from enum import Enum
from typing import Optional

from memory.store import memory
from utils.logger import logger


class Tier(str, Enum):
    INNER_CIRCLE  = "inner_circle"   # best friends — full slang, banter, vulnerability
    FRIENDS       = "friends"        # good friends — mostly full Ken
    ACQUAINTANCES = "acquaintances"  # people Ken knows — moderate, no heavy slang
    FAMILY        = "family"         # family / elders — warm, respectful, no macha
    PUBLIC        = "public"         # strangers / internet — clean, professional-ish


TIER_SPEECH_RULES: dict[str, dict] = {
    Tier.INNER_CIRCLE: {
        "slang":      True,
        "kannada":    True,
        "banter":     True,
        "tone":       "full Ken — machha, dei, bro, swearing, all of it. completely unfiltered.",
    },
    Tier.FRIENDS: {
        "slang":      True,
        "kannada":    True,
        "banter":     True,
        "tone":       "close friend mode — relaxed, warm, casual Kannada fine.",
    },
    Tier.ACQUAINTANCES: {
        "slang":      False,
        "kannada":    False,
        "banter":     False,
        "tone":       "friendly but measured. no heavy slang. light and genuine.",
    },
    Tier.FAMILY: {
        "slang":      False,
        "kannada":    False,
        "banter":     False,
        "tone":       "warm and respectful. no macha, machha, swearing, or rough humour. caring but composed.",
    },
    Tier.PUBLIC: {
        "slang":      False,
        "kannada":    False,
        "banter":     False,
        "tone":       "clean, grounded. light humour okay. professional-casual.",
    },
}

# Legacy contact_type strings → tier mapping (backwards compat with existing store entries)
CTYPE_TO_TIER: dict[str, str] = {
    "friend":     Tier.FRIENDS,
    "family":     Tier.FAMILY,
    "adult":      Tier.FAMILY,
    "colleague":  Tier.ACQUAINTANCES,
    "unknown":    Tier.PUBLIC,
    "inner":      Tier.INNER_CIRCLE,
    "inner_circle": Tier.INNER_CIRCLE,
    "acquaintance": Tier.ACQUAINTANCES,
    "public":     Tier.PUBLIC,
}

_KV_PREFIX = "sg:"


class SocialGraph:
    """Singleton — call via `social_graph` module-level object."""

    # ── CRUD ──────────────────────────────────────────────────────────────

    def upsert(
        self,
        contact_id: str,
        *,
        name: str = "",
        tier: Optional[str] = None,
        relationship: str = "",
        topics: Optional[list[str]] = None,
    ) -> None:
        entry = self._get(contact_id)
        if name:
            entry["name"] = name
        if tier:
            entry["tier"] = CTYPE_TO_TIER.get(tier.lower(), tier)
        if relationship:
            entry["relationship"] = relationship
        if topics:
            existing = set(entry.get("topics_discussed", []))
            entry["topics_discussed"] = list(existing | set(topics))
        entry["updated_at"] = datetime.utcnow().isoformat()
        entry["contact_id"] = contact_id
        self._save(contact_id, entry)

    def bump_interaction(self, contact_id: str, by: int = 1) -> None:
        entry = self._get(contact_id)
        entry["interaction_count"] = entry.get("interaction_count", 0) + by
        # Auto-upgrade trust score slightly with each interaction
        entry["trust_score"] = min(100, entry.get("trust_score", 50) + 1)
        self._save(contact_id, entry)

    def get_tier(self, contact_id: str) -> str:
        """Return tier string, falling back to contact_type KV, then PUBLIC."""
        entry = self._get(contact_id)
        if entry.get("tier"):
            return entry["tier"]
        # fallback: check legacy contact_type key
        ctype = memory.get_contact_type(contact_id)
        if ctype and ctype != "unknown":
            return CTYPE_TO_TIER.get(ctype, Tier.PUBLIC)
        return Tier.PUBLIC

    def get_speech_rules(self, contact_id: str) -> dict:
        tier = self.get_tier(contact_id)
        return TIER_SPEECH_RULES.get(tier, TIER_SPEECH_RULES[Tier.PUBLIC])

    def get_contact(self, contact_id: str) -> dict:
        return self._get(contact_id)

    def set_tier(self, contact_id: str, tier: str) -> None:
        normalized = CTYPE_TO_TIER.get(tier.lower(), tier.lower())
        self.upsert(contact_id, tier=normalized)
        # Keep legacy contact_type in sync too
        memory.set_contact_type(contact_id, tier.lower())
        logger.info(f"SocialGraph: {contact_id} -> tier={normalized}")

    def build_tone_instruction(self, contact_id: str) -> str:
        """Return a 1-sentence tone instruction to inject into AI prompt."""
        tier   = self.get_tier(contact_id)
        rules  = TIER_SPEECH_RULES.get(tier, TIER_SPEECH_RULES[Tier.PUBLIC])
        return rules["tone"]

    # ── Internal ──────────────────────────────────────────────────────────

    def _key(self, contact_id: str) -> str:
        return f"{_KV_PREFIX}{contact_id}"

    def _get(self, contact_id: str) -> dict:
        raw = memory.get(self._key(contact_id), "{}")
        try:
            return json.loads(raw)
        except Exception:
            return {}

    def _save(self, contact_id: str, entry: dict) -> None:
        memory.set(self._key(contact_id), json.dumps(entry))


social_graph = SocialGraph()
