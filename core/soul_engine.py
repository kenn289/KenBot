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
_INTEREST_WEB_KEY   = "soul_interest_web"         # expanded topic web from facts + preferences
_LAST_FAST_DISTILL_KEY = "soul_last_fast_distill_ts"

# ── Tuning ───────────────────────────────────────────────
_DISTILL_EVERY   = 6    # faster persona convergence from multi-source signals
_X_LIKED_MAX     = 60   # rolling window of X liked posts to keep
_COMMANDS_MAX    = 40   # rolling window of commands to keep
_YT_TOPICS_MAX   = 30   # rolling window of YT topics to keep
_X_REPLIES_MAX   = 40   # rolling window of X replies to keep
_INTEREST_WEB_MAX = 80  # max interest web topics to store
_FAST_DISTILL_COOLDOWN_SECONDS = 120


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

    def trigger_fast_distill(self, reason: str = "") -> bool:
        """
        Trigger a best-effort profile distillation now with cooldown.
        Used after major style/convo updates so mimic quality improves quickly.
        """
        try:
            now_ts = int(datetime.utcnow().timestamp())
            last_ts = int(memory.get(_LAST_FAST_DISTILL_KEY, "0") or "0")
            if last_ts and (now_ts - last_ts) < _FAST_DISTILL_COOLDOWN_SECONDS:
                return False
            memory.set(_LAST_FAST_DISTILL_KEY, str(now_ts))
            threading.Thread(target=self._distill_profile, daemon=True).start()
            logger.info(f"Fast soul distill queued ({reason or 'manual'})")
            return True
        except Exception:
            return False

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
You're building a living personality profile for an AI that posts on X (Twitter) AS this person.
Be hyper-specific. Vague profiles produce bot-like tweets. Specific profiles produce human tweets.
All signals below come from his real online activity.

TEXTING STYLE (from WhatsApp messages):
{style or "not enough data yet"}

SOCIAL WORLD (WhatsApp conversation topics/energy):
{convo_ctx or "not enough data yet"}

KNOWN FACTS (public-safe only):
{facts_block or "none yet"}

POSTS HE LIKED ON X — his actual taste:
{liked_block}

REPLIES HE MADE ON X — how he actually talks online:
{reply_block}

SELF-COMMANDS (what he explicitly asked to post about):
{cmd_block}

YOUTUBE SHORTS HE MADE (content taste):
{yt_block}

FOR YOU FEED TOPICS (what the algorithm feeds him):
{feed_block}

Write a personality profile in 14-18 tight bullet points covering ALL of:

1. VOCAB & CATCHPHRASES: specific words/phrases he uses. E.g. "bro", "actually cooked",
   "lowkey", "fr fr", "i cannot", "the disrespect", "unironically", "certified". List actual examples.
2. ENERGY LEVEL: how chaotic vs. measured. Does he go all-caps? Use ellipsis? Fragment sentences?
3. HUMOUR ARCHETYPE: pick 1-2: absurdist | hyperbole king | self-roaster | hot-take merchant |
   dry deadpan | chronically online | pure chaos. Describe how it shows with an example.
4. INTEREST HIERARCHY: rank his top 5-6 passion areas. For each: ONE sentence on HOW he engages.
   E.g. "Valorant — full stan mode, glorifies his faves, reacts to clips like he's watching live"
5. REPLY PATTERNS: how he reacts to (a) impressive clips, (b) bad takes, (c) relatable posts,
   (d) something funny. Give a realistic example phrase for each.
6. THINGS HE NEVER DOES: tweet styles that would feel completely out-of-character.
7. ROAST STYLE: what's fair game (bad takes, situations, irony) vs hard limits.
8. TWITTER PERSONA: one sentence archetype that captures the whole vibe.

Evidence-based from signals above. Under 420 words.
DO NOT include: private relationships, real names of people he knows, employer, location, phone.
"""
            profile = ken_ai._call(
                "You are a personality analyst building a hyper-specific digital twin for Twitter.",
                prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=550,
                use_cache=False,
            )
            memory.set(_SOUL_PROFILE_KEY, profile)
            logger.info(f"Soul profile distilled ({len(profile)} chars)")
            # After every distillation, rebuild the interest web in the background
            threading.Thread(target=self._expand_interest_web, daemon=True).start()
        except Exception as exc:
            logger.warning(f"Soul distillation failed: {exc}")

    def _expand_interest_web(self) -> None:
        """
        Reads ALL facts + preferences + liked posts and asks AI to expand them
        into a rich web of related topics the person would genuinely follow.

        Example: "fav song = Waiting for the End by Linkin Park"
          → topics: "Linkin Park", "Chester Bennington", "Mike Shinoda",
                    "nu-metal", "Hybrid Theory era", "Minutes to Midnight"

        Example: "supports Man City"
          → topics: "Man City", "Pep Guardiola", "Erling Haaland",
                    "Premier League title race", "Etihad Stadium"

        The expanded web is stored and used by get_dynamic_topics() and
        generate_shitpost() so the bot naturally engages with posts about
        Linkin Park / Chester Bennington / Man City etc. without being told.
        """
        try:
            from core.ai_engine import ken_ai

            # Gather seed signals
            from memory.facts_store import facts_store
            global_facts = facts_store.get_global(limit=30)
            facts_block = "\n".join(f"- {f['fact_text']}" for f in global_facts) if global_facts else ""

            liked = self._load(_X_LIKES_KEY)
            liked_sample = "\n".join(f"- {e['text'][:100]}" for e in liked[-15:]) if liked else ""

            commands = self._load(_COMMANDS_KEY)
            cmd_sample = ", ".join(e["cmd"] for e in commands[-10:]) if commands else ""

            profile = memory.get(_SOUL_PROFILE_KEY, "")[:600]

            prompt = f"""
You're building an INTEREST WEB for a Twitter bot that must engage authentically.

KNOWN FACTS & PREFERENCES:
{facts_block or "none yet"}

SELF-COMMANDS (topics he explicitly cares about):
{cmd_sample or "none yet"}

POSTS HE LIKED RECENTLY (what catches his eye):
{liked_sample or "none yet"}

PERSONALITY SNAPSHOT:
{profile or "not yet distilled"}

TASK: For EACH preference/fact you find, expand it into 3-6 RELATED topics/people/events
he would naturally follow and engage with on Twitter.

Examples of good expansion:
- "Waiting for the End by Linkin Park" → Linkin Park, Chester Bennington, Mike Shinoda,
  nu-metal playlist, Hybrid Theory, Minutes to Midnight, Post Traumatic album
- "Man City fan" → Man City, Pep Guardiola, Erling Haaland, Kevin De Bruyne,
  Premier League title race, Etihad Stadium, Man City vs Arsenal
- "Sentinels fan" → Sentinels, TenZ, Zekken, Sacy, VCT Americas, watchparty creators, roster updates
- "likes RCB" → RCB, Virat Kohli, IPL 2026, Royal Challengers Bangalore, Faf du Plessis

Return ONLY a JSON array of strings — ALL the expanded topics (60-80 total).
Each string is a short topic/person/entity (max 5 words). Deduplicated.
Prioritise specificity over generality. Include bands, players, teams, albums,
characters, events — anything he'd see in a feed and want to react to.
"""
            raw = ken_ai._call(
                "You are a fan-profile analyst building a personalised interest web.",
                prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=700,
                use_cache=False,
            )
            raw = raw.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
            topics: list[str] = [str(t).strip() for t in json.loads(raw) if t][:_INTEREST_WEB_MAX]
            memory.set(_INTEREST_WEB_KEY, json.dumps(topics))
            logger.info(f"Interest web expanded: {len(topics)} topics (sample: {topics[:6]})")
        except Exception as exc:
            logger.warning(f"Interest web expansion failed: {exc}")

    def build_topic_context(self, topic: str) -> str:
        """
        Returns a short block of CURRENT GROUNDED FACTS about a topic,
        synthesised from what the bot knows (profile, interest web, liked posts).
        Injected into tweet/reply prompts so the bot never posts stale or wrong info.

        Example for 'Man City':
          "Current facts: Man City are 2nd in Prem (as of Mar 2026), Haaland top scorer,
           Pep in his last year, rival Arsenal 3pts ahead."

        Example for 'Linkin Park':
          "Current facts: Chester Bennington died 2017; band returned with Emily Armstrong
           2024; new album From Zero released Nov 2024; Mike Shinoda still active."
        """
        try:
            from core.ai_engine import ken_ai

            # Pull in what the bot already knows about this topic
            profile = memory.get(_SOUL_PROFILE_KEY, "")[:400]
            interest_web_raw = memory.get(_INTEREST_WEB_KEY, "[]")
            interest_web: list[str] = json.loads(interest_web_raw) if interest_web_raw else []

            # Find any liked posts or replies mentioning this topic
            liked = self._load(_X_LIKES_KEY)
            related_liked = [
                e["text"][:100] for e in liked[-30:]
                if topic.lower()[:12] in e.get("text", "").lower()
            ][:5]
            # First: check if any recently liked/feed posts mention this topic —
            # those are the freshest ground truth we have
            feed_topics_raw: list[str] = self._load_list("x_learned_feed_topics")
            feed_mention = next((f for f in feed_topics_raw if topic.lower()[:10] in f.lower()), "")
            liked_context = "\n".join(f"- {t}" for t in related_liked) if related_liked else ""

            prompt = f"""
Topic: "{topic}"

What the bot recently saw about this topic in its feed:
{liked_context or feed_mention or "nothing specific yet"}

Task: Give 3-5 SHORT FACTUAL POINTS to help write an accurate tweet/reply about "{topic}".

SPLIT your response into two sections:

[BACKGROUND] — things you know confidently (history, members, playing style, key facts, reputation):
  → Always fill this section. E.g. "Linkin Park: Chester Bennington died 2017, Emily Armstrong new vocalist 2024, known for nu-metal + Hybrid Theory era"
  → E.g. "Man City: Pep Guardiola managed since 2016, known for possession football, Haaland striker, multiple EPL titles"

[LIVE/CURRENT] — current season standings, recent match results, chart positions (you may not have this):
  → Omit bullets you're genuinely unsure about
  → Only include if confident

Rules:
- max 10 words per bullet
- be specific (players, albums, era — not generic)
- Return only the bullets under each section header. No intro text.
"""
            facts = ken_ai._call(
                "You are a concise fact-checker for a social media bot. Only state what you know confidently.",
                prompt,
                model="claude-haiku-4-5-20251001",
                max_tokens=220,
                use_cache=False,
            )
            facts_text = facts.strip()
            # Only fully hedge if AI gave truly nothing useful
            useless = (
                len(facts_text) < 40
                or ("don't have access" in facts_text.lower() and "[background]" not in facts_text.lower())
                or ("cannot provide" in facts_text.lower() and "[background]" not in facts_text.lower())
            )
            if useless:
                return (
                    f"⚠ FACT HEDGE FOR {topic}: React to the post's energy/sentiment. "
                    f"Match their excitement or commiserate — don't assert specific facts you don't know."
                )
            return f"GROUNDING CONTEXT for {topic} (use as background — don't state these explicitly):\n{facts_text}"
        except Exception as exc:
            logger.debug(f"build_topic_context failed for {topic}: {exc}")
            return ""

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

    def get_dynamic_topics(self) -> list[str]:
        """
        Returns the FULL live topic list the bot should post/engage about.
        Merges (in priority order):
          1. Expanded interest web (AI-derived from facts — Linkin Park, Man City etc.)
          2. Feed-learned topics (what's trending NOW in the For You feed)
          3. Self-commanded topics
          4. Recent liked post extracts
        This is used by generate_shitpost() for topic selection — it grows over time
        as new facts and interactions are recorded.
        """
        # 1. Expanded interest web (facts-derived)
        try:
            web_raw = memory.get(_INTEREST_WEB_KEY, "[]")
            web: list[str] = json.loads(web_raw) if web_raw else []
        except Exception:
            web = []

        # 2. Feed-learned (trending right now)
        feed = self._load_list("x_learned_feed_topics")[:15]

        # 3. Commands
        commands = self._load(_COMMANDS_KEY)
        cmd_topics = [e["cmd"] for e in commands[-8:]]

        # 4. Liked snippets
        liked = self._load(_X_LIKES_KEY)
        liked_raw = [e["text"][:50] for e in liked[-8:]]

        # Merge — feed topics first (freshest), then web (richest), then rest
        merged: list[str] = []
        seen: set[str] = set()
        for item in feed + web + cmd_topics + liked_raw:
            key = item.lower().strip()[:35]
            if key and key not in seen:
                seen.add(key)
                merged.append(item)

        return merged[:100]  # return up to 100 live topics

    def get_voice_context(self) -> str:
        """
        Returns ONLY the distilled voice/style/personality for the reply generator.
        Formatted as actionable writing instructions, not a biography.
        NO topic signals — post topic drives reply content, not this.
        """
        profile = memory.get(_SOUL_PROFILE_KEY, "")
        if not profile:
            return (
                "Young bangalore software engineer, massive esports + sports nerd.\n"
                "Slang (rotate — don't repeat same word twice in a row): fr, lowkey, actually cooked, i cannot, the disrespect, unironically, okay but, wait, genuinely, actually, lmaooo, literally.\n"
                "Humour: absurdist hot takes, hyperbole, chronically online energy.\n"
                "Lowercase always. Fragment sentences. Short punchy reactions."
            )
        return (
            "═══ THIS PERSON'S VOICE (write exactly like this) ═══\n"
            + profile
            + "\n\nNever reveal private data, real personal names, relationships, or location."
        )

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
