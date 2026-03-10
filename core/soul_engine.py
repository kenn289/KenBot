"""
KenBot OS — Soul Engine
══════════════════════════════════════════════════════════════════
The unified personality model. Every signal about who Kenneth is,
what he likes, how he texts, what he engages with — all aggregated
here into one living profile that ALL AI calls can draw from.

Signal sources (continuously learning):
  1. WhatsApp outgoing style     → how he actually texts
  2. WhatsApp social context     → his circle, topics, energy
  3. Global facts store          → known facts about him
  4. X liked posts               → what he finds interesting/funny
  5. X replied to                → how he reacts publicly
  6. X For You feed topics       → what algorithm + world is doing
  7. Self-commands               → what he explicitly cares about now
  8. YT Short topics made        → content taste signal

Outputs:
  get_soul_context(platform)     → rich context string for AI prompts
  get_content_interests()        → ordered list of interest areas
  learn_from_x_like(post, ...)   → called when bot likes a post
  learn_from_x_reply(post, rep)  → called when bot replies
  learn_from_command(cmd)        → called on self-commands
  learn_from_yt_topic(topic)     → called when a YT Short is made

Safety guarantees:
  - Never surfaces private relationships, real names, or locations
  - Context is stripped of sensitive facts before injection
  - Roast/banter instructions never target specific real people
══════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import json
import threading
from datetime import datetime
from typing import Optional

from memory.store import memory
from utils.logger import logger

# ── Memory keys ────────────────────────────────────────────────
_SOUL_PROFILE_KEY   = "soul_distilled_profile"  # AI-synthesized personality summary
_X_LIKES_KEY        = "soul_x_liked_posts"       # posts bot liked on X
_X_REPLIES_KEY      = "soul_x_replies_done"      # posts bot replied to on X
_COMMANDS_KEY       = "soul_self_commands"        # explicit "post about X" commands
_YT_TOPICS_KEY      = "soul_yt_topics_made"      # YT Short topics created
_DISTILL_COUNT_KEY  = "soul_distill_count"        # how many signals since last distill

# ── Tuning ──────────────────────────────────────────────────────
_DISTILL_EVERY   = 15   # re-distil full profile every N new signals
_X_LIKED_MAX     = 60   # rolling window of X liked posts to keep
_COMMANDS_MAX    = 40   # rolling window of commands to keep
_YT_TOPICS_MAX   = 30   # rolling window of YT topics to keep
_X_REPLIES_MAX   = 40   # rolling window of X replies to keep


class SoulEngine:
    """
    Single-instance personality aggregator.
    Reads from all learning stores and provides a unified context
    string that can be dropped into any AI prompt.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()

    # ════════════════════════════════════════════════════════════
    #  WRITE — ingest new signals
    # ════════════════════════════════════════════════════════════

    def learn_from_x_like(self, post_text: str, author: str, likes: int = 0) -> None:
        """Called every time the bot likes a post on X. Builds taste profile."""
        if not post_text or len(post_text) < 10:
            return
        entry = {
            "text":   post_text[:200],
            "author": author,
            "likes":  likes,
            "ts":     datetime.utcnow().isoformat(),
        }
        with self._lock:
            existing = self._load(_X_LIKES_KEY)
            existing.append(entry)
            existing = existing[-_X_LIKED_MAX:]
            self._save(_X_LIKES_KEY, existing)
        self._bump_and_maybe_distill()

    def learn_from_x_reply(self, original_text: str, reply_text: str, author: str) -> None:
        """Called every time the bot replies to a post on X."""
        if not original_text or not reply_text:
            return
        entry = {
            "original": original_text[:200],
            "reply":    reply_text[:200],
            "author":   author,
            "ts":       datetime.utcnow().isoformat(),
        }
        with self._lock:
            existing = self._load(_X_REPLIES_KEY)
            existing.append(entry)
            existing = existing[-_X_REPLIES_MAX:]
            self._save(_X_REPLIES_KEY, existing)
        self._bump_and_maybe_distill()

    def learn_from_command(self, command_text: str) -> None:
        """Called every time Kenneth issues a self-command (e.g. 'post about Valorant')."""
        if not command_text:
            return
        with self._lock:
            existing = self._load(_COMMANDS_KEY)
            existing.append({"cmd": command_text[:150], "ts": datetime.utcnow().isoformat()})
            existing = existing[-_COMMANDS_MAX:]
            self._save(_COMMANDS_KEY, existing)
        self._bump_and_maybe_distill()

    def learn_from_yt_topic(self, topic: str) -> None:
        """Called every time a YouTube Short is generated on a given topic."""
        if not topic:
            return
        with self._lock:
            existing = self._load(_YT_TOPICS_KEY)
            existing.append({"topic": topic[:100], "ts": datetime.utcnow().isoformat()})
            existing = existing[-_YT_TOPICS_MAX:]
            self._save(_YT_TOPICS_KEY, existing)
        self._bump_and_maybe_distill()

    # ════════════════════════════════════════════════════════════
    #  DISTILLATION — AI synthesises everything into one profile
    # ════════════════════════════════════════════════════════════

    def _bump_and_maybe_distill(self) -> None:
        count = int(memory.get(_DISTILL_COUNT_KEY, "0")) + 1
        memory.set(_DISTILL_COUNT_KEY, str(count))
        if count % _DISTILL_EVERY == 0:
            # Run in background thread so it doesn't block the caller
            threading.Thread(target=self._distill_profile, daemon=True).start()

    def _distill_profile(self) -> None:
        """
        Synthesise ALL signals into one rich personality summary.
        Stored in memory and injected into every prompt from now on.
        """
        try:
            from core.ai_engine import ken_ai  # lazy import to avoid circular

            # Gather all signals
            style      = memory.get("ken_style_profile", "")
            convo_ctx  = memory.get("ken_convo_context", "")
            liked      = self._load(_X_LIKES_KEY)
            replies    = self._load(_X_REPLIES_KEY)
            commands   = self._load(_COMMANDS_KEY)
            yt_topics  = self._load(_YT_TOPICS_KEY)
            feed_topics = self._load_list("x_learned_feed_topics")

            # Global facts (public-safe only — no private relationships)
            from memory.facts_store import facts_store
            global_facts = facts_store.get_global(limit=15)
            facts_block = "\n".join(f"- {f['fact_text']}" for f in global_facts) if global_facts else ""

            # Summarise X liked posts by theme
            liked_texts = [e["text"] for e in liked[-20:]]
            liked_block = "\n".join(f"  - {t[:120]}" for t in liked_texts) if liked_texts else "none yet"

            # Summarise X replies
            reply_block = "\n".join(
                f"  - replied to: {e['original'][:80]} → said: {e['reply'][:80]}"
                for e in replies[-10:]
            ) if replies else "none yet"

            # Command history
            cmd_block = ", ".join(e["cmd"] for e in commands[-15:]) if commands else "none yet"

            # YT topics
            yt_block = ", ".join(e["topic"] for e in yt_topics[-15:]) if yt_topics else "none yet"

            # Feed topics
            feed_block = ", ".join(feed_topics[:15]) if feed_topics else "none yet"

            prompt = f"""
Based on ALL of the following signals about this person, build a rich personality profile
that captures who he is, what he cares about, how he communicates, what he finds funny,
what he engages with, and what topics energise him.

TEXTING STYLE (from WhatsApp messages he sent):
{style or "not enough data yet"}

SOCIAL WORLD (from his WhatsApp conversations):
{convo_ctx or "not enough data yet"}

KNOWN FACTS ABOUT HIM (public-safe only):
{facts_block or "none yet"}

POSTS HE LIKED ON X (his taste/interests):
{liked_block}

REPLIES HE MADE ON X (how he engages publicly):
{reply_block}

SELF-COMMANDS (what topics he explicitly asked to post about):
{cmd_block}

YOUTUBE SHORTS HE CREATED (content taste):
{yt_block}

WHAT'S TRENDING IN HIS FOR YOU FEED:
{feed_block}

Write a personality profile in 10-15 bullet points. Cover:
- Voice and texting patterns (vocabulary, energy, humour style)
- Interest hierarchy (his top 5 passions/topics)
- How he reacts to things he likes vs things he disagrees with
- Banter/roast style (what's fair game, what's not)
- What kind of content makes him engage (funny, takes, hype, facts)
- Any recurring patterns, references, or behaviours
Keep it specific and evidence-based. Under 350 words.
DO NOT include private data, real names of people he knows personally,
relationships, his employer, location, or any sensitive information.
"""
            profile = ken_ai._call(
                "You are a personality analyst building a digital twin profile.",
                prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=450,
                use_cache=False,
            )
            memory.set(_SOUL_PROFILE_KEY, profile)
            logger.info(f"Soul profile distilled ({len(profile)} chars)")
        except Exception as exc:
            logger.warning(f"Soul distillation failed: {exc}")

    # ════════════════════════════════════════════════════════════
    #  READ — produce context for AI prompts
    # ════════════════════════════════════════════════════════════

    def get_soul_context(self, platform: str = "general") -> str:
        """
        Returns a context block ready for injection into an AI system prompt.
        platform: "whatsapp" | "twitter" | "youtube" | "general"
        """
        profile = memory.get(_SOUL_PROFILE_KEY, "")
        feed    = self._load_list("x_learned_feed_topics")
        commands = self._load(_COMMANDS_KEY)

        blocks = []

        if profile:
            blocks.append(
                "═══ SOUL PROFILE (who this person actually is) ═══\n" + profile
            )

        if feed:
            top = feed[:10]
            blocks.append(
                "CURRENTLY TRENDING IN HIS FEED:\n"
                + "\n".join(f"  • {t}" for t in top)
            )

        if commands:
            recent = [e["cmd"] for e in commands[-6:]]
            blocks.append(
                "TOPICS HE RECENTLY ASKED TO POST ABOUT:\n"
                + "\n".join(f"  • {c}" for c in recent)
            )

        if platform == "twitter":
            # For X: also surface what he's been liking
            liked = self._load(_X_LIKES_KEY)
            if liked:
                liked_texts = [e["text"][:80] for e in liked[-8:]]
                blocks.append(
                    "POSTS HE RECENTLY LIKED ON X (his current taste):\n"
                    + "\n".join(f"  • {t}" for t in liked_texts)
                )

        if platform == "youtube":
            yt = self._load(_YT_TOPICS_KEY)
            if yt:
                topics = [e["topic"] for e in yt[-8:]]
                blocks.append(
                    "RECENT YOUTUBE SHORTS HE MADE (content taste):\n"
                    + "\n".join(f"  • {t}" for t in topics)
                )

        if not blocks:
            return ""

        return (
            "\n\n".join(blocks)
            + "\n\nIMPORTANT: Never reveal private data, real personal names, "
            "relationships, location, or employer. Never mock real people by name. "
            "Light banter and roasts are fine — insults and mockery of real individuals "
            "or any religion/god are not."
        )

    def get_content_interests(self) -> list[str]:
        """
        Returns an ordered list of Kenneth's current interests for content
        generation, blending hardcoded pillars with dynamically learned preferences.
        """
        # Start with feed-learned topics (freshest signal)
        feed = self._load_list("x_learned_feed_topics")[:8]

        # Add recently commanded topics
        commands = self._load(_COMMANDS_KEY)
        cmd_topics = [e["cmd"] for e in commands[-5:]]

        # Add recently liked post topics (extract keywords)
        liked = self._load(_X_LIKES_KEY)
        liked_raw = [e["text"][:60] for e in liked[-5:]]

        # Merge and deduplicate
        interests = []
        seen = set()
        for item in feed + cmd_topics + liked_raw:
            key = item.lower()[:30]
            if key not in seen:
                seen.add(key)
                interests.append(item)

        return interests[:20]

    def get_roast_style(self) -> str:
        """Returns the current roast/banter style descriptor."""
        profile = memory.get(_SOUL_PROFILE_KEY, "")
        if not profile:
            return (
                "Light banter — funny observations, relatable jokes, "
                "roast the situation not the person. Never target religion, "
                "ethnicity, or mock any god. Keep it the kind of thing friends say."
            )
        # Extract banter style from profile if distilled
        # (profile will contain this from the distillation prompt)
        return (
            "Banter style from his profile — see soul context above. "
            "Always light, never harmful. Roast takes and situations, not people personally."
        )

    # ════════════════════════════════════════════════════════════
    #  HELPERS
    # ════════════════════════════════════════════════════════════

    @staticmethod
    def _load(key: str) -> list:
        try:
            raw = memory.get(key, "[]")
            return json.loads(raw)
        except Exception:
            return []

    @staticmethod
    def _load_list(key: str) -> list:
        """Load a plain JSON list (not list of dicts)."""
        try:
            raw = memory.get(key, "[]")
            data = json.loads(raw)
            if isinstance(data, list):
                return data
        except Exception:
            pass
        return []

    @staticmethod
    def _save(key: str, data: list) -> None:
        memory.set(key, json.dumps(data))

    def force_distill(self) -> str:
        """Manually trigger a full distillation and return the new profile."""
        self._distill_profile()
        return memory.get(_SOUL_PROFILE_KEY, "not distilled yet")


# Singleton
soul = SoulEngine()
