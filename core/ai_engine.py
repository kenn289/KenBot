"""
Ken ClawdBot â€” AI Engine
Claude Sonnet powers all of Ken's responses.
Free-tier aware: caches repeated prompts, uses Haiku for cheap tasks.
"""
from __future__ import annotations

import hashlib
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

import anthropic
import openai as openai_client
from google import genai as google_genai

from config.ken_personality import (
    IDENTITY,
    MOODS,
    RESPONSE_RULES,
    CONTENT_PILLARS,
    REMINDER_STYLE,
)
from config.settings import settings
from core.mood import mood_manager
from utils.logger import logger
from utils.helpers import retry_api

# â”€â”€ Model routing â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
MODEL_SONNET = "claude-sonnet-4-5-20250929"    # 90% of tasks
MODEL_HAIKU  = "claude-haiku-4-5-20251001"    # Quick / cheap tasks (reminders, short replies)
MODEL_OPUS   = "claude-opus-4-20250514"       # Deep content only

MAX_TOKENS_REPLY   = 50    # WhatsApp / X replies — 1 sentence, punchy
MAX_TOKENS_CONTENT = 1200  # Posts, scripts
MAX_TOKENS_THREAD  = 800   # Tweet threads

# â”€â”€ Response cache (avoid burning API on identical prompts) â”€â”€
CACHE_DB = settings.root_dir / "memory" / "response_cache.db"
CACHE_DB.parent.mkdir(parents=True, exist_ok=True)


class KenAI:
    """
    All AI calls go through this class.
    Responsible for: prompt construction, model selection,
    caching, rate-limit protection, response cleaning.
    """

    def __init__(self) -> None:
        self.client = anthropic.Anthropic(api_key=settings.anthropic_api_key)
        self._oai = openai_client.OpenAI(api_key=settings.openai_api_key) if settings.openai_api_key else None
        if settings.gemini_api_key:
            self._gemini = google_genai.Client(api_key=settings.gemini_api_key)
        else:
            self._gemini = None
        self._db = sqlite3.connect(str(CACHE_DB), check_same_thread=False)
        self._init_cache()

    # â”€â”€ Cache â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    def _init_cache(self) -> None:
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS response_cache (
                hash    TEXT PRIMARY KEY,
                prompt  TEXT,
                reply   TEXT,
                model   TEXT,
                created TEXT
            )
            """
        )
        self._db.commit()

    def _cache_key(self, prompt: str) -> str:
        return hashlib.md5(prompt.strip().encode()).hexdigest()

    def _from_cache(self, key: str) -> Optional[str]:
        row = self._db.execute(
            "SELECT reply FROM response_cache WHERE hash=?", (key,)
        ).fetchone()
        return row[0] if row else None

    def _to_cache(self, key: str, prompt: str, reply: str, model: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO response_cache VALUES (?,?,?,?,?)",
            (key, prompt[:500], reply, model, datetime.utcnow().isoformat()),
        )
        self._db.commit()

    # ── Style learning ────────────────────────────────────
    STYLE_LEARN_EVERY = 8  # re-summarise style every N messages from Kenneth

    def learn_from_message(self, message: str) -> None:
        """Store a raw message Kenneth typed; rebuild style profile every N calls."""
        from memory.store import memory
        raw = memory.get("style_raw_msgs", "[]")
        try:
            msgs = json.loads(raw)
        except Exception:
            msgs = []
        msgs.append(message)
        msgs = msgs[-50:]
        memory.set("style_raw_msgs", json.dumps(msgs))

        count = int(memory.get("style_learn_count", "0")) + 1
        memory.set("style_learn_count", str(count))
        if count % self.STYLE_LEARN_EVERY == 0:
            self._update_style_profile(msgs)

    def _update_style_profile(self, msgs: list[str]) -> None:
        """Run Haiku to extract Kenneth's texting patterns, save to kv_store."""
        from memory.store import memory
        sample = "\n".join(f"- {m}" for m in msgs[-30:])
        prompt = (
            f"These are real WhatsApp messages typed by the person this bot is based on:\n"
            f"{sample}\n\n"
            "In 6-8 bullet points, describe his texting style concretely: vocabulary, "
            "sentence length, emoji use, energy level, specific slang or catchphrases, "
            "how he reacts to things, any recurring patterns. Under 200 words."
        )
        try:
            style = self._call(
                "You are a style analyst. Extract communication patterns from WhatsApp messages.",
                prompt,
                model=MODEL_HAIKU,
                max_tokens=250,
                use_cache=False,
            )
            memory.set("ken_style_profile", style)
            logger.info("Style profile updated")
        except Exception as exc:
            logger.warning(f"Style profile update failed: {exc}")

    def _get_style_summary(self) -> str:
        """Retrieve the learned style profile (empty string until enough data)."""
        from memory.store import memory
        return memory.get("ken_style_profile", "")

    # ── Convo-context learning (from other people's messages) ─────────────────
    CONVO_LEARN_EVERY = 15  # re-summarise convo context every N incoming messages

    def learn_from_convo(self, speaker: str, message: str) -> None:
        """Store an incoming message from someone else; rebuild convo-context every N calls."""
        from memory.store import memory
        raw = memory.get("convo_raw_msgs", "[]")
        try:
            msgs = json.loads(raw)
        except Exception:
            msgs = []
        msgs.append(f"{speaker}: {message}")
        msgs = msgs[-80:]  # keep last 80 lines
        memory.set("convo_raw_msgs", json.dumps(msgs))

        count = int(memory.get("convo_learn_count", "0")) + 1
        memory.set("convo_learn_count", str(count))
        if count % self.CONVO_LEARN_EVERY == 0:
            self._update_convo_context(msgs)

    def _update_convo_context(self, msgs: list[str]) -> None:
        """Ask Haiku to summarise the topics and vibe of Kenneth's social world."""
        from memory.store import memory
        sample = "\n".join(msgs[-40:])
        prompt = (
            f"These are real WhatsApp conversations from Kenneth's chats (format 'speaker: message'):\n"
            f"{sample}\n\n"
            "In 5-7 bullet points, summarise:\n"
            "- What topics does Kenneth's circle talk about most (games, people, events, jokes)?\n"
            "- What's the general vibe/energy of these convos?\n"
            "- Any recurring references, memes, or inside topics?\n"
            "- What does Kenneth respond to / engage with most?\n"
            "Keep it under 200 words. Be specific, not generic."
        )
        try:
            context = self._call(
                "You are an analyst extracting social context from WhatsApp conversations.",
                prompt,
                model=MODEL_HAIKU,
                max_tokens=280,
                use_cache=False,
            )
            memory.set("ken_convo_context", context)
            logger.info("Convo context updated")
        except Exception as exc:
            logger.warning(f"Convo context update failed: {exc}")

    def _get_convo_context(self) -> str:
        """Retrieve the convo-context summary (empty string until enough data)."""
        from memory.store import memory
        return memory.get("ken_convo_context", "")

    # ── News / trends context ─────────────────────────────
    _news_cache: dict = {}   # {"headlines": str, "fetched_at": datetime}

    def _get_news_context(self) -> str:
        """Fetch top headlines once per hour, return as a short brief."""
        from datetime import datetime, timedelta
        import feedparser

        cached = self._news_cache
        if cached.get("fetched_at") and datetime.utcnow() - cached["fetched_at"] < timedelta(hours=1):
            return cached.get("headlines", "")

        feeds = [
            "https://feeds.bbci.co.uk/news/world/rss.xml",
            "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",
            "https://sportstar.thehindu.com/cricket/feed/",
        ]
        headlines = []
        for url in feeds:
            try:
                d = feedparser.parse(url)
                for entry in d.entries[:3]:
                    headlines.append(entry.get("title", "").strip())
            except Exception:
                pass

        brief = "; ".join(h for h in headlines[:8] if h)
        self._news_cache = {"headlines": brief, "fetched_at": datetime.utcnow()}
        logger.debug(f"News context refreshed: {len(headlines)} headlines")
        return brief

    # â”€â”€ Prompt builders â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # â”€â”€ Tone detector â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    @staticmethod
    def _classify_message(message: str, is_real_group: bool = False) -> str:
        """
        Returns: 'serious' | 'rant' | 'casual' | 'skip' | 'mute'
        - serious : crisis/distress, full support mode
        - rant    : bestie venting, listen + empathy
        - casual  : normal banter
        - skip    : trivial reaction, Ken stays quiet
        - mute    : told to back off — Ken goes silent for 30 min
        """
        import random
        msg = message.lower().strip()
        words = msg.split()

        # Told to shut up / back off — mute for a while
        shutup = [
            "stop","stfu","shut up","shutup","leave me alone","stop talking",
            "dont talk to me","don't talk to me","stop messaging","stop texting",
            "go away","get lost","back off","enough","stop it","not now",
            "i said stop","please stop","just stop","stop replying",
        ]
        if any(s in msg for s in shutup):
            return "mute"

        # Short reactions in real groups — mostly skip
        if is_real_group and len(words) <= 3:
            noise = {"lol","lmao","haha","ok","okay","bro","bhai","da","yaar",
                     "nice","😂","💀","🤣","fr","facts","true","nah","yep","yup",
                     "same","gg","💯","👀","😭","bruh"}
            if set(words) & noise:
                return "skip"
            if random.random() < 0.35:   # 35% random quiet in real groups
                return "skip"

        crisis = [
            "depressed","depression","anxiety attack","died","death","funeral",
            "accident","hospital","broke up","breakup","lost my","help me",
            "i need help","emergency","urgent","dont want to be here",
            "want to end","cant go on",
        ]
        if any(s in msg for s in crisis):
            return "serious"

        rant = [
            "rant","venting","just listen","im so tired","i'm so tired",
            "sick of this","so done","can't take","cannot take","so frustrated",
            "this is bullshit","everything is wrong","nobody understands",
            "my boss","my manager","my parents are","failed my","failed the",
            "got rejected","they rejected me","so stressed","too stressed",
            "struggling with","rough day","rough week","bad day","bad week",
            "interview went","exam result","got fired","laid off",
            "money issue","money problem","in debt","not okay","im not okay",
            "i'm not okay","honestly bro","bro honestly","i hate this",
        ]
        if any(s in msg for s in rant):
            return "rant"

        return "casual"

    @staticmethod
    def _is_serious_message(message: str) -> bool:
        return KenAI._classify_message(message) in ("serious", "rant")

    def _system_prompt(
        self,
        context: str = "general",
        group_name: str = "",
        is_dm: bool = False,
        serious_mode: str = "casual",  # "serious" | "rant" | "casual"
        contact_type: str = "unknown",  # "friend" | "family" | "adult" | "colleague" | "unknown"
        chat_id: str = "",
    ) -> str:
        from config.ken_personality import CONTACT_TONE_RULES
        mood_profile = mood_manager.current_profile()
        is_real_group = group_name.lower() in [g.lower() for g in settings.ken_real_groups]

        if serious_mode == "serious":
            persona_section = (
                "Someone's hurting or in a hard place. Be a real friend — present, honest, no performance. "
                "Say the right thing not the comfortable thing. Short and genuine."
            )
        elif serious_mode == "rant":
            persona_section = (
                "They're venting. Let them. Acknowledge it like a real person would, not a therapist. "
                "If you have something real to offer say it once, briefly. Don't fix, don't advise unless they ask."
            )
        elif is_dm:
            persona_section = (
                "Private DM. Be yourself — a bit more open than in a group, still understated. "
                "Match their energy. If they're being real, be real back."
            )
        elif is_real_group:
            persona_section = (
                "Close group chat. Relax. Be yourself fully — warm, low-key funny, genuine. "
                "Not performing, just present. Like actually texting your boys."
            )
        else:
            persona_section = (
                "General group or public. More reserved, observational. "
                "Say things when you have something worth saying. Don't fill silence."
            )

        # Contact-type tone override
        contact_tone = CONTACT_TONE_RULES.get(contact_type, "")
        contact_block = f"\nCONTACT TYPE OVERRIDE: {contact_tone}\n" if contact_tone else ""

        # Fun facts from this specific chat
        facts_block = ""
        if chat_id:
            from memory.store import memory as _mem
            facts = _mem.get_fun_facts(chat_id)
            if facts:
                facts_lines = "\n".join(f"- {f['speaker']}: {f['fact']}" for f in facts[-10:])
                facts_block = f"\nFUN FACTS shared about Kenneth in this chat (use naturally, never expose in other chats):\n{facts_lines}\n"

        style_block = ""
        style_summary = self._get_style_summary()
        if style_summary:
            style_block = f"\nLEARNED STYLE (adapt your replies to match these patterns — this is how he actually texts):\n{style_summary}\n"

        soul_block = ""
        try:
            from core.soul_engine import soul as _soul
            soul_ctx = _soul.get_soul_context("whatsapp")
            if soul_ctx:
                soul_block = f"\n{soul_ctx}\n"
        except Exception:
            pass

        news = self._get_news_context()
        news_block = f"\nCURRENT DATE: {datetime.now().strftime('%d %B %Y')}\nWHAT'S HAPPENING (recent headlines — reference naturally when relevant, don't force it):\n{news}\n" if news else f"\nCURRENT DATE: {datetime.now().strftime('%d %B %Y')}\n"

        return f"""
{IDENTITY}

═══════════════════════════
CURRENT MOOD: {mood_profile['name'].upper()}
{mood_profile['tone_modifier']}
═══════════════════════════
{news_block}
GROUP MODE: {persona_section}
{contact_block}{facts_block}{style_block}{soul_block}
{RESPONSE_RULES}
""".strip()

    # â”€â”€ Core call â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€
    # Note: no @retry_api here â€” fallback chain handles errors internally
    def _call(
        self,
        system: str,
        user_message: str,
        model: str = MODEL_SONNET,
        max_tokens: int = MAX_TOKENS_REPLY,
        use_cache: bool = True,
    ) -> str:
        cache_key = self._cache_key(f"{model}|{system[:200]}|{user_message}")

        if use_cache:
            cached = self._from_cache(cache_key)
            if cached:
                logger.debug("AI cache hit")
                return cached

        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            text = response.content[0].text.strip()
        except anthropic.APIError as exc:
            logger.warning(f"Anthropic unavailable ({exc.__class__.__name__}), falling back to Gemini")
            text = self._call_gemini(system, user_message)

        if use_cache:
            self._to_cache(cache_key, user_message, text, model)

        logger.debug(f"AI [{model}] â†’ {len(text)} chars")
        return text

    def _call_openai(self, system: str, user_message: str, max_tokens: int = 300) -> str:
        """OpenAI fallback."""
        if not self._oai:
            raise RuntimeError("OpenAI not configured.")
        response = self._oai.chat.completions.create(
            model="gpt-4o-mini",
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content.strip()

    def _call_gemini(self, system: str, user_message: str) -> str:
        """Gemini free-tier fallback (gemini-2.0-flash-lite)."""
        if not self._gemini:
            raise RuntimeError("Gemini not configured.")
        full_prompt = f"{system}\n\n---\n{user_message}"
        response = self._gemini.models.generate_content(
            model="gemini-2.0-flash-lite",
            contents=full_prompt,
        )
        return response.text.strip()

    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•
    #  PUBLIC METHODS
    # â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•â•

    def reply_to_message(
        self,
        message: str,
        sender_name: str = "",
        group_name: str = "",
        context_history: str = "",
        is_dm: bool = False,
        chat_id: str = "",
        is_mentioned: bool = False,
        contact_type: str = "unknown",
    ) -> str:
        from memory.store import memory
        from datetime import datetime, timedelta

        # Check active mute for this chat
        if chat_id:
            mute_until = memory.get(f"mute_{chat_id}", "")
            if mute_until:
                try:
                    # Lift mute if they @mentioned Ken or said his name
                    if is_mentioned or "ken" in message.lower():
                        memory.set(f"mute_{chat_id}", "")
                        logger.info(f"Mute lifted in {chat_id} — Ken was mentioned")
                    elif datetime.utcnow() < datetime.fromisoformat(mute_until):
                        return ""   # still muted
                    else:
                        memory.set(f"mute_{chat_id}", "")  # expired, clear it
                except Exception:
                    pass

        mood_manager.apply_context(message)
        mode = self._classify_message(message, is_real_group=bool(group_name))

        if mode == "mute":
            # Store 30-min mute for this chat
            if chat_id:
                until = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
                memory.set(f"mute_{chat_id}", until)
                logger.info(f"Ken muted in {chat_id} for 30 min")
            return ""
        if mode == "skip":
            return ""   # Ken stays quiet
        system = self._system_prompt(
            group_name=group_name,
            is_dm=is_dm,
            serious_mode=mode,
            contact_type=contact_type,
            chat_id=chat_id,
        )
        history_block = f"\nRecent chat context:\n{context_history}\n" if context_history else ""
        prompt = f"{history_block}{'[' + sender_name + ']: ' if sender_name else ''}{message}"
        # model + token budget based on mode
        if mode == "serious":
            model, max_tok = MODEL_SONNET, 250
        elif mode == "rant":
            model, max_tok = MODEL_HAIKU, 120
        else:
            model, max_tok = MODEL_HAIKU, MAX_TOKENS_REPLY

        # ── Live news injection — ALWAYS, for any message ────────────────────
        # Never rely on keyword matching — Google News handles relevance.
        # Short pure-chitchat (≤3 words, no question intent) → skip to save time.
        import re as _re
        _msg_lower = message.lower()
        _word_count = len(message.split())
        _has_question_intent = any(c in _msg_lower for c in [
            "?", "who", "what", "when", "where", "how", "why",
            "is ", "are ", "did ", "does ", "will ", "can ",
        ])
        _is_short_chitchat = _word_count <= 3 and not _has_question_intent
        if not _is_short_chitchat:
            try:
                from core.news_fetcher import news_fetcher as _nf
                _search_query = _re.sub(r'^hey\s*ken\s*', '', message, flags=_re.IGNORECASE).strip()
                # Primary facts search
                _ctx = _nf.get_news_context_for_claude(_search_query)
                # Secondary opinions search — only for opinionated/subjective messages
                _opinion_ctx = ""
                _is_opinion_topic = any(w in _msg_lower for w in [
                    "best", "worst", "overrated", "underrated", "goat", "better", "worse",
                    "debate", "who is", "do you think", "opinion", "think about",
                    "rank", "rate", "worth", "should", "can", "will",
                ])
                if _is_opinion_topic and _nf.tavily_search:
                    _op_items = _nf.tavily_search(
                        f"{_search_query} opinions community reddit what people think", n=4
                    )
                    if _op_items:
                        _op_lines = ["WHAT PEOPLE ARE SAYING:"]
                        for _it in _op_items[:4]:
                            _snip = (_it.get("summary") or "")[:180]
                            if _it.get("title") == "Direct Answer":
                                _op_lines.append(f"  SUMMARY: {_snip}")
                            else:
                                _op_lines.append(f"  - {_it['title']} [{_it['source']}]")
                                if _snip:
                                    _op_lines.append(f"    {_snip}")
                        _opinion_ctx = "\n".join(_op_lines)
                if _ctx or _opinion_ctx:
                    _combined = "\n\n".join(filter(None, [_ctx, _opinion_ctx]))
                    system = system + (
                        "\n\n━━━━━━ LIVE RESEARCH ━━━━━━\n"
                        + _combined
                        + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                        "You have the facts AND what people are saying above. "
                        "Do NOT say you lack real-time data — you just looked it up. "
                        "Read the facts, consider the community opinions, then respond as Kenneth "
                        "with HIS actual take — short, casual, grounded in what's real."
                    )
                    if model == MODEL_HAIKU:
                        model, max_tok = MODEL_SONNET, 300
            except Exception as _e:
                logger.warning(f"live news inject failed: {_e}")
        # ─────────────────────────────────────────────────────────────────────

        return self._call(system, prompt, model=model, max_tokens=max_tok)

    def generate_tweet(self, topic: str, style: str = "hot take") -> str:
        """
        Generate a single tweet (≤280 chars) on a given topic.
        style options: 'hot take' | 'joke' | 'reaction' | 'thread_opener'
        Incorporates learned personal style and social context.
        """
        style_summary = self._get_style_summary()
        convo_context = self._get_convo_context()

        style_block = ""
        if style_summary:
            style_block = f"\nHOW THIS PERSON ACTUALLY TEXTS (match this voice exactly):\n{style_summary}\n"

        convo_block = ""
        if convo_context:
            convo_block = f"\nHIS SOCIAL WORLD / WHAT HIS CIRCLE TALKS ABOUT (use this for authenticity, don't force it):\n{convo_context}\n"

        soul_block = ""
        try:
            from core.soul_engine import soul as _soul
            soul_ctx = _soul.get_soul_context("twitter")
            if soul_ctx:
                soul_block = f"\n{soul_ctx}\n"
        except Exception:
            pass

        system = (
            "You are ghostwriting a tweet for a real Gen Z person. "
            "Sound like a human who actually lives this — not a brand, not a bot, not a motivational page. "
            "Raw, casual, unfiltered. Use lowercase, abbreviations, skip punctuation where it feels natural. "
            "Never use hashtags like a press release. If the topic is personal/niche, lean into it hard."
            f"{style_block}{convo_block}{soul_block}"
        )
        prompt = (
            f"Write ONE tweet about: {topic}\n"
            f"Tone: {style}\n"
            "Rules:\n"
            "- Under 260 characters\n"
            "- Sound like something you'd actually post at 2am not something a social media manager wrote\n"
            "- 1-2 hashtags that real people actually use for this topic (e.g. #Valorant #VCT #Cricket #F1 #AI #Coding)\n"
            "- No quotation marks. Just output the tweet text.\n"
            "- NEVER mention real personal details: no full name, location, employer, school, relationships\n"
            "- Keep it public-safe — opinions/takes/fan content only"
        )
        raw = self._call(system, prompt, model=MODEL_HAIKU, max_tokens=300, use_cache=False)
        from utils.helpers import truncate
        return truncate(raw, 280)

    def generate_tweet_thread(self, topic: str, num_tweets: int = 5) -> list[str]:
        """
        Generate a tweet thread (numbered 1/n ... n/n) on a topic.
        Returns list of tweet strings. Uses learned style + convo context.
        """
        style_summary = self._get_style_summary()
        convo_context = self._get_convo_context()

        style_block = f"\nHOW THIS PERSON TEXTS:\n{style_summary}\n" if style_summary else ""
        convo_block = f"\nHIS WORLD/TOPICS:\n{convo_context}\n" if convo_context else ""

        system = (
            "You are ghostwriting a tweet thread for a real Gen Z person. "
            "Each tweet should sound like a natural continuation — casual, direct, lowercase where it fits. "
            "Not a blog post broken into tweets. Actual thoughts."
            f"{style_block}{convo_block}"
        )
        prompt = (
            f"Write a {num_tweets}-tweet thread about: {topic}\n"
            "Format: return ONLY a JSON array of strings, one string per tweet, no extra text.\n"
            "Each tweet ≤265 characters. Hashtags only on the last tweet if at all.\n"
            "Example format: [\"Tweet 1...\", \"Tweet 2...\"]"
        )
        raw = self._call(
            system, prompt, model=MODEL_SONNET, max_tokens=MAX_TOKENS_THREAD, use_cache=False
        )
        # Parse JSON array
        try:
            tweets = json.loads(raw)
            if isinstance(tweets, list):
                from utils.helpers import truncate
                return [truncate(t, 280) for t in tweets[:num_tweets]]
        except json.JSONDecodeError:
            logger.warning("Thread JSON parse failed, falling back to line split")
            lines = [l.strip() for l in raw.split("\n") if l.strip()]
            from utils.helpers import truncate
            return [truncate(l, 280) for l in lines[:num_tweets]]
        return []

    # ── Self-chat command handler ──────────────────────────────────────
    def handle_command(self, instruction: str) -> str:
        """
        Called when Kenneth types "hey ken <instruction>" in his own WhatsApp chat.
        Uses Claude to understand intent, then executes and returns a reply string.
        """
        from memory.store import memory

        instr_lower = instruction.lower().strip()

        # ── Status set: "status at work" / "status gaming rn" ──
        if instr_lower.startswith("status "):
            status_text = instruction[7:].strip()
            memory.set("ken_status", status_text)
            return f"status set: \"{status_text}\" — intro messages updated"

        # ── Mood: "mood chill" / "mood hype" ──
        if instr_lower.startswith("mood "):
            from core.mood import mood_manager
            mood_text = instruction[5:].strip().lower()
            try:
                mood_manager.force_mood(mood_text, lock_minutes=120)
                return f"mood locked to {mood_text} for 2h"
            except Exception:
                return f"couldn't set mood to {mood_text} — valid: chill, hype, tired, focused, unhinged, sad, neutral"

        # ── Tag contact: "tag 91xxxxx@c.us as family" / "tag amma as family" ──
        if instr_lower.startswith("tag "):
            import re
            tag_body = instruction[4:].strip()
            parts = re.split(r"\s+as\s+", tag_body, maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                identifier = parts[0].strip()
                ctype = parts[1].strip().lower()
                valid = {"family", "friend", "adult", "colleague", "unknown"}
                if ctype not in valid:
                    return f"valid types: {', '.join(sorted(valid))} — got \"{ctype}\""
                # Allow JIDs directly or store by normalized name
                contact_id = identifier if "@" in identifier else f"name:{identifier.lower()}"
                memory.set_contact_type(contact_id, ctype)
                return f"tagged \"{identifier}\" as {ctype} — tone will adjust"
            return "format: tag <name/number> as <family|friend|adult|colleague>"

        # ── What did u learn / show style ──
        if any(x in instr_lower for x in ["what did u learn", "what have u learned", "show learned", "show style", "what do u know"]):
            style = memory.get("ken_style_profile", "")
            convo = memory.get("ken_convo_context", "")
            raw_count = len(json.loads(memory.get("style_raw_msgs", "[]")))
            convo_count = len(json.loads(memory.get("convo_raw_msgs", "[]")))
            lines = [f"msgs collected: {raw_count} from u, {convo_count} incoming\n"]
            if style:
                lines.append(f"your style:\n{style}")
            else:
                lines.append(f"style: not built yet (need {max(0, 8 - raw_count)} more msgs from u)")
            if convo:
                lines.append(f"\nyour world:\n{convo}")
            return "\n".join(lines)

        # ── Inbox ──
        if any(x in instr_lower for x in ["inbox", "who messaged", "what did i miss"]):
            summary = memory.get("inbox_log", "")
            return summary if summary else "inbox is empty"

        # ── Tweet / Post ──
        tweet_triggers = ["post", "tweet", "post about", "tweet about", "say"]
        if any(instr_lower.startswith(t) for t in tweet_triggers):
            topic = instruction
            for t in tweet_triggers:
                topic = topic.replace(t, "", 1).strip()
            if not topic:
                return "post about what?"
            try:
                from channels.twitter.poster import twitter
                if not twitter.ready:
                    return "twitter not set up yet — login still needed"
                tweet_text = self.generate_tweet(topic)
                result = twitter.post_tweet(tweet_text)
                if result:
                    return f"posted: {tweet_text}"
                return "tweet failed to post"
            except Exception as e:
                return f"tweet error: {e}"

        # ── YouTube Short ──
        yt_triggers = ["yt", "youtube", "short", "yt short", "youtube short", "make a video", "make video"]
        if any(instr_lower.startswith(t) for t in yt_triggers):
            topic = instruction
            for t in sorted(yt_triggers, key=len, reverse=True):
                if topic.lower().startswith(t):
                    topic = topic[len(t):].strip()
                    break
            if not topic:
                return "yt short about what?"
            try:
                import threading
                def _run():
                    from channels.youtube.content_gen import yt_content
                    from channels.youtube.uploader import yt_uploader
                    pkg = yt_content.generate_video_package(topic)
                    vid = yt_uploader.upload_package(pkg)
                    if vid:
                        memory.queue_notification(f"yt short live: https://youtu.be/{vid}\n{topic}")
                    else:
                        memory.queue_notification(f"yt short failed for: {topic}")
                threading.Thread(target=_run, daemon=True).start()
                return f"generating yt short about \"{topic}\" — will DM when live"
            except Exception as e:
                return f"yt error: {e}"

        # ── Trivia / Community Games ──
        if any(instr_lower.startswith(t) for t in ["trivia", "give me a trivia", "trivia question"]):
            return self._generate_trivia()

        if instr_lower.startswith("roast"):
            return self._generate_roast(instruction)

        if any(instr_lower.startswith(t) for t in ["debate", "debate this", "let's debate"]):
            topic = instruction[7:].strip() if instr_lower.startswith("debate ") else ""
            return self._generate_debate(topic)

        if instr_lower.startswith("poll") or instr_lower.startswith("make a poll"):
            topic = instruction.split(" ", 2)[-1]
            return self._generate_poll(topic)

        # ── Trending / Cricket ──
        if any(x in instr_lower for x in ["what's trending", "whats trending", "what is trending", "trending"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.get_trending_news()

        if any(x in instr_lower for x in ["cricket update", "cricket news", "cricket score"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.get_cricket_update()

        if any(x in instr_lower for x in ["tech news", "tech update"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.format_headlines("tech", n=5)

        if any(x in instr_lower for x in ["india news", "what's happening in india"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.format_headlines("india", n=5)

        if any(x in instr_lower for x in ["gaming news", "game news"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.format_headlines("gaming", n=5)

        if any(x in instr_lower for x in ["esports news", "esports update", "valorant news", "vct news"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.format_headlines("esports", n=5)

        if any(x in instr_lower for x in ["f1", "formula 1", "formula one", "grand prix", "qualifying", "race result", "motorsport"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.format_headlines("f1", n=5)

        if any(x in instr_lower for x in ["sports news", "football news", "sports update"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.format_headlines("sports", n=5)

        if any(x in instr_lower for x in ["top news", "latest news", "news"]):
            from core.news_fetcher import news_fetcher
            return news_fetcher.format_headlines("top", n=5)

        # ── Analytics (private) ──
        if any(x in instr_lower for x in ["analytics", "how am i doing", "post stats", "stats"]):
            from analytics.performance import analytics
            from growth.engagement_optimizer import engagement_optimizer
            return analytics.format_briefing() + "\n\n" + engagement_optimizer.format_briefing()

        # ── Trend ideas (private) ──
        if any(x in instr_lower for x in ["trend ideas", "content ideas", "what should i post"]):
            from content.idea_factory import idea_factory
            return idea_factory.format_briefing()

        # ── Daily briefing ──
        if any(x in instr_lower for x in ["daily briefing", "briefing", "morning report"]):
            return self._daily_briefing()

        # ── Reddit opportunities ──
        if any(x in instr_lower for x in ["reddit", "reddit ideas", "reddit opportunities"]):
            from growth.reddit_engine import reddit_engine
            return reddit_engine.format_opportunities()

        # ── Reply sniper (manual trigger) ──
        if any(x in instr_lower for x in ["reply sniper", "snipe", "sniper", "run sniper"]):
            try:
                from growth.influencer_reply_engine import influencer_reply_engine
                from channels.twitter.poster import twitter
                tweets = influencer_reply_engine.fetch_viral_tweets()
                if not tweets:
                    return "no viral targets found right now, try again later"
                t = tweets[0]
                reply = influencer_reply_engine.generate_reply_to(t["text"], author=t.get("author", ""))
                if not reply:
                    return "couldn't generate a reply for the top tweet"
                result = twitter.post_tweet(reply)
                if result:
                    memory.set(f"replied_{t['id']}", "1")
                    return f"replied to @{t.get('author','?')}:\n{reply}"
                return f"generated reply but posting failed:\n{reply}"
            except Exception as _e:
                return f"sniper error: {_e}"

        # ── Fallback: let Claude figure it out ──
        style = memory.get("ken_style_profile", "")
        system = (
            "You are Ken's personal AI assistant, talking directly to Ken in private. "
            "He sent you a command or question. Be direct, concise, helpful. "
            "If it's a task you can't execute (needs external data, can't browse etc), say so plainly. "
            "If it's a question, answer it. Max 3 sentences."
            + (f"\n\nHis texting style: {style}" if style else "")
        )
        return self._call(system, instruction, model=MODEL_HAIKU, max_tokens=300, use_cache=False)

    def generate_yt_title_and_description(self, topic: str, content_type: str = "commentary") -> dict:
        """
        Generate YouTube video title, description, and tags.
        Returns dict: {title, description, tags}
        """
        system = self._system_prompt(context="youtube_metadata")
        prompt = (
            f"Generate YouTube metadata for a video about: {topic}\n"
            f"Content type: {content_type} (commentary/reaction/analysis)\n"
            "Return ONLY valid JSON in this format:\n"
            '{"title": "...", "description": "...", "tags": ["tag1", "tag2", ...]}\n'
            "Title: catchy, â‰¤70 chars, no clickbait.\n"
            "Description: 150-300 chars, natural, includes relevant keywords.\n"
            "Tags: 8-15 relevant tags."
        )
        raw = self._call(system, prompt, model=MODEL_SONNET, max_tokens=600, use_cache=True)
        # Strip markdown code fences if AI wrapped the JSON
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
        cleaned = cleaned.rstrip("`").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            # Try extracting the first {...} block
            import re
            m = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
            logger.warning("YT metadata JSON parse failed")
            return {"title": topic, "description": "", "tags": []}

    def generate_yt_short_slides(self, topic: str) -> dict:
        """
        Generate punchy slide content for a YouTube Short.
        Returns: {hook, slides: [...], cta, vibe}
        """
        system = (
            f"{IDENTITY}\n\n"
            "You make viral YouTube Shorts — shitpost style, hot takes, meme energy. "
            "Think: loud, punchy, scroll-stopping. 15-45 seconds total. "
            "Each slide is ONE punchy line that fills the screen. No fluff. "
            "Topics rotate across: gaming (Valorant/TenZ), cricket (Kohli/RCB), F1 (Max/Carlos), "
            "AI/tech takes, dev/coding memes, pop culture, desi/Indian life, crack jokes, "
            "trending internet drama, hot takes on anything."
        )
        prompt = (
            f"Topic: {topic}\n\n"
            "Create a YouTube Short with punchy text slides. Return ONLY valid JSON:\n"
            '{"hook": "opening line (1 punchy sentence, under 8 words)", '
            '"slides": ["slide1", "slide2", "slide3", "slide4"], '
            '"cta": "follow/subscribe CTA (short)", '
            '"vibe": "hype|dark|funny|unhinged|facts"}\n\n'
            "Rules:\n"
            "- Each slide: max 7 words, ALL CAPS for emphasis words\n"
            "- hook must be insane/controversial/shocking/hilarious\n"
            "- Tech/AI/meme/dev topics: lean into humor and relatability\n"
            "- Gaming/sports: hype + stan energy\n"
            "- vibe controls the visual style\n"
            "- 4-6 slides total (no more)\n"
            "- sound like a bored bangalore bro who knows too much"
        )
        raw = self._call(system, prompt, model=MODEL_SONNET, max_tokens=400, use_cache=False)
        cleaned = raw.strip()
        if cleaned.startswith("```"):
            cleaned = "\n".join(cleaned.split("\n")[1:])
        cleaned = cleaned.rstrip("`").strip()
        try:
            return json.loads(cleaned)
        except json.JSONDecodeError:
            import re
            m = re.search(r'\{.*\}', cleaned, re.DOTALL)
            if m:
                try:
                    return json.loads(m.group())
                except Exception:
                    pass
            # fallback
            return {
                "hook": topic.upper(),
                "slides": ["this actually happened", "no one talks about this", "but here we are"],
                "cta": "follow for more",
                "vibe": "unhinged"
            }

    def generate_yt_script(self, topic: str, duration_minutes: int = 5) -> str:
        """
        Generate a YouTube video script.
        ~130 words/minute → duration * 130 words target.
        """
        word_count = duration_minutes * 130
        system = self._system_prompt(context="youtube_script")
        prompt = (
            f"Write a YouTube video script about: {topic}\n"
            f"Target length: ~{word_count} words ({duration_minutes} min spoken)\n"
            "Format: Hook (15s) â†’ Main content â†’ CTA\n"
            "Write as if Ken is speaking â€” his voice, his opinions.\n"
            "NO stage directions, NO [Music], NO [Cut to]. Just the spoken words."
        )
        return self._call(
            system, prompt, model=MODEL_SONNET, max_tokens=MAX_TOKENS_CONTENT, use_cache=False
        )

    def generate_shitpost(self, group_name: str = "") -> str:
        """Generate a random unprompted shitpost/joke to drop in a real group."""
        import random
        mood = mood_manager.current()
        vibes = [
            "make a funny observation about bangalore life, traffic, or the heat",
            "drop a savage Valorant hot take or rant about bad teammates",
            "say something dumb and funny about football or Man City",
            "share a random chaotic thought like a bored bangalore boy texting",
            "roast something completely random in a funny way",
            "drop a one-liner joke with bangalore bro energy",
            "share a random unpopular opinion about DC, Marvel, or gaming",
            "drop a meme-worthy shower thought nobody asked for",
            "say something about Kohli that will definitely start an argument",
            "rant about something trivial like it's the end of the world",
        ]
        vibe = random.choice(vibes)
        system = (
            f"{IDENTITY}\n\n"
            "You're texting in your friend group on WhatsApp. Nobody asked you anything. "
            "You just felt like saying something random. Keep it very short (1-3 lines max), "
            "use bangalore/indian bro texting style â€” lowercase, casual, chaotic energy. "
            "No need to address anyone or explain yourself. Just drop it like a random unprompted text."
        )
        prompt = f"Randomly {vibe}. Current mood: {mood}. Make it feel totally natural and unprompted."
        return self._call(system, prompt, model=MODEL_HAIKU, max_tokens=120, use_cache=False)

    def generate_convo_starter(self, group_name: str = "") -> str:
        """Kick off a random discussion topic in a real group â€” feels like Ken just thought of something."""
        import random
        mood = mood_manager.current()
        topics = [
            "ask the group a spicy this-or-that about Valorant agents or players",
            "start a debate about who's the actual GOAT â€” TenZ, Aspas, or someone else",
            "ask if Man City will ever be the same without a specific era player",
            "drop a controversial DC vs Marvel take and ask who agrees",
            "ask the group what they think Kohli's legacy actually is â€” greatest or overrated?",
            "ask everyone what the most broken agent in Valorant right now is and why",
            "start a debate: is ranked Valorant actually playable or is it a social experiment",
            "ask what everyone's most unhinged late-night food order has been",
            "ask the group: best Indian city to live in besides Bangalore, go",
            "pose a random hypothetical like 'if you could only play one game for the rest of your life'",
            "ask for the worst tech job interview horror story anyone's had",
            "start the classic Bangalore debate â€” namma metro or ola/uber?",
            "ask if anyone actually watches anime anymore or is that phase dead",
            "drop a 'hot take: [topic]' style opener and ask the group to fight you",
        ]
        topic = random.choice(topics)
        system = (
            f"{IDENTITY}\n\n"
            "You're texting your friend group and you just thought of something worth discussing. "
            "Start the conversation naturally â€” 1-3 lines max. "
            "Bangalore bro texting style: lowercase, casual, maybe a bit of chaos. "
            "End with a question or a provocative statement that makes people want to reply. "
            "Do NOT say 'guys' or 'everyone'. Just drop the topic like you're thinking out loud."
        )
        prompt = f"Naturally {topic}. Current mood: {mood}. Make it feel like a random thought that just hit."
        return self._call(system, prompt, model=MODEL_HAIKU, max_tokens=130, use_cache=False)

    def generate_reminder(self, task: str, due: str = "") -> str:
        """Generate a self-reminder message in Ken's voice."""
        system = f"{IDENTITY}\n\n{REMINDER_STYLE}"
        prompt = (
            f"Write a reminder note TO YOURSELF (Ken) about: {task}\n"
            f"{'Due: ' + due if due else ''}\n"
            "1-3 sentences max. WhatsApp format."
        )
        return self._call(system, prompt, model=MODEL_HAIKU, max_tokens=150, use_cache=False)

    def pick_content_topic(self) -> dict:
        """Let AI pick the best content topic right now based on pillars."""
        from config.ken_personality import CONTENT_PILLARS
        pillars_str = json.dumps(CONTENT_PILLARS, indent=2)
        system = self._system_prompt(context="content_planning")
        prompt = (
            f"Given these content pillars:\n{pillars_str}\n\n"
            "Pick ONE topic/angle that would perform well on Twitter and YouTube TODAY.\n"
            "Rotate across ALL pillars — don't always pick gaming. Consider:\n"
            "  - Valorant scene (ROTATE players, not only TenZ): fns IGL breakdowns, boaster/Karmine hype,\n"
            "    tarik streaming moments, shanks/yay/nAts/aspas/Derke/Demon1 highlights,\n"
            "    Sentinels (TenZ/Zekken/Sacy/pANcada), VCT Americas/EMEA/Pacific results, agent meta/patch takes\n"
            "  - AI/tech (AI drama, new model releases, vibe coding, cursor, layoffs)\n"
            "  - Cricket/F1 (Kohli, RCB, Max Verstappen, Carlos Sainz, race results, IPL)\n"
            "  - Memes/internet culture (viral formats, Twitter drama, trending topics)\n"
            "  - Dev/coding life (programmer memes, leetcode, software engineer relatable)\n"
            "  - Pop culture (Netflix, Bollywood, Marvel, DC, movies, music)\n"
            "  - Indian/desi life (startup culture, Bangalore, food delivery, traffic jokes)\n"
            "  - Hot takes / crack jokes (shower thoughts, absurd takes, anything funny)\n"
            "Return ONLY JSON: {\"topic\": \"...\", \"angle\": \"...\", \"platform\": \"both|twitter|youtube\"}"
        )
        raw = self._call(system, prompt, model=MODEL_HAIKU, max_tokens=200, use_cache=False)
        try:
            return json.loads(raw)
        except Exception:
            fallbacks = [
                {"topic": "fns Valorant", "angle": "best IGL callouts in VCT", "platform": "both"},
                {"topic": "boaster VCT", "angle": "Karmine Corp hype energy", "platform": "twitter"},
                {"topic": "TenZ Sentinels", "angle": "clutch highlight of the week", "platform": "both"},
                {"topic": "aspas LOUD", "angle": "most insane stat line this split", "platform": "twitter"},
            ]
            import random as _r
            return _r.choice(fallbacks)


    # ── Community game helpers ─────────────────────────────────────────

    def _generate_trivia(self) -> str:
        # Pull recent headlines so trivia questions can be about current events
        live_block = ""
        try:
            from core.news_fetcher import news_fetcher as _nf
            headlines = _nf.format_headlines("top", n=5, force=True)
            if headlines:
                live_block = (
                    "\n\nRecent headlines for inspiration (you MAY use these for topical questions):\n"
                    + headlines
                )
        except Exception:
            pass
        system = (
            f"{IDENTITY}\n\n"
            "You're playing trivia with your friends on WhatsApp. "
            "Ask ONE trivia question about cricket, gaming/esports, Bangalore, Bollywood, Indian tech culture, "
            "or current events. Format: question + 4 options (A/B/C/D) + answer hidden at the bottom as '||Answer: X||'. "
            "Keep it fun and medium difficulty — not too easy, not obscure."
            + live_block
        )
        return self._call(system, "give me a trivia question", model=MODEL_HAIKU, max_tokens=200, use_cache=False)

    def _generate_roast(self, instr: str = "") -> str:
        _lower = instr.lower().strip()
        # Extract target: "roast <name>", "roast me", "roast yourself"
        if _lower.startswith("roast "):
            target = instr[6:].strip()
        else:
            target = "me"
        if not target:
            target = "me"
        if target.lower() in ("yourself", "urself"):
            target = "yourself"

        system = (
            f"{IDENTITY}\n\n"
            "You are roasting someone in a WhatsApp group. Be direct and funny. "
            "1-3 punchy lines max. Bangalore bro comedy energy. "
            "RULES: "
            "Do NOT say 'nobody asked', 'who asked', 'wasn't requested', or any meta-commentary. "
            "Do NOT ask for more context, more info, or say 'tell me more about them'. "
            "Do NOT say 'give me more context'. Just roast immediately based on just the name. "
            "If you only have a name, roast them on generic things — group chat habits, how they probably "
            "act, typical funny stereotypes. Make it up confidently. "
            "Keep it friendly, not cruel. Start the roast on line 1, no warm-up."
        )
        return self._call(system, f"roast {target}", model=MODEL_HAIKU, max_tokens=150, use_cache=False)

    def _generate_debate(self, topic: str = "") -> str:
        from core.content_brain import content_brain
        if not topic:
            topic_dict = content_brain.hot_take()
            topic = topic_dict["seed"]

        # ── Step 1: gather FACTS (recent results, stats, verified news) ──
        facts_block = ""
        opinions_block = ""
        try:
            from core.news_fetcher import news_fetcher as _nf
            # Pass 1 — hard facts: scores, results, rankings, recent events
            facts_items = _nf.tavily_search(f"{topic} latest results stats news", n=5)
            if facts_items:
                lines = ["FACTS & RECENT RESULTS:"]
                for it in facts_items[:5]:
                    if it.get("title") == "Direct Answer":
                        lines.append(f"  ANSWER: {it['summary'][:300]}")
                    else:
                        snippet = (it.get("summary") or "")[:200]
                        lines.append(f"  - {it['title']} [{it['source']}]")
                        if snippet:
                            lines.append(f"    {snippet}")
                facts_block = "\n".join(lines)

            # Pass 2 — community opinions: Reddit threads, fan takes, analyst sentiment
            opinion_items = _nf.tavily_search(
                f"{topic} opinions community reddit fans thoughts debate", n=5
            )
            if opinion_items:
                lines = ["WHAT PEOPLE ARE SAYING (opinions / community sentiment):"]
                for it in opinion_items[:5]:
                    if it.get("title") == "Direct Answer":
                        lines.append(f"  SUMMARY: {it['summary'][:300]}")
                    else:
                        snippet = (it.get("summary") or "")[:200]
                        lines.append(f"  - {it['title']} [{it['source']}]")
                        if snippet:
                            lines.append(f"    {snippet}")
                opinions_block = "\n".join(lines)
        except Exception as e:
            logger.warning(f"[debate] research failed: {e}")

        # ── Step 2: build the research brief ──
        research = ""
        if facts_block or opinions_block:
            parts = []
            if facts_block:
                parts.append(facts_block)
            if opinions_block:
                parts.append(opinions_block)
            research = (
                "\n\n━━━━━━ RESEARCH BRIEF ━━━━━━\n"
                + "\n\n".join(parts)
                + "\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            )

        # ── Step 3: prompt Claude to think as Kenneth and form a real opinion ──
        system = (
            f"{IDENTITY}\n\n"
            "TASK: You've been handed a research brief with real facts AND what the community thinks "
            "about this topic. Read it carefully. Now respond as Kenneth — not as a neutral debate bot.\n\n"
            "HOW TO RESPOND:\n"
            "- First internalize: what do the FACTS say? What is the actual truth?\n"
            "- Then consider: what's the popular opinion? Do you agree or disagree? Why?\n"
            "- Then give YOUR take as Kenneth — opinionated, grounded in the facts, sounding like a "
            "real person texting in a group chat, not a pundit.\n"
            "- 2-4 sentences max. No bullet points. Casual lowercase.\n"
            "- Do NOT end with a question. Do NOT ask the group what they think. Just state your view.\n"
            "- Do NOT hedge or do 'both sides'. Kenneth has actual opinions. Pick a lane and own it.\n"
            "- If the facts clearly prove something (e.g. NRG won Champions 2025), say it confidently "
            "and use it to anchor your take.\n"
            + research
        )
        model = MODEL_SONNET  # always Sonnet — this needs actual reasoning
        return self._call(system, f"give your take on: {topic}", model=model, max_tokens=250, use_cache=False)

    def _generate_poll(self, topic: str = "") -> str:
        from core.content_brain import content_brain
        poll = content_brain.poll_options(topic)
        return (
            f"*{poll['q']}*\n\n"
            f"1️⃣  {poll['a']}\n"
            f"2️⃣  {poll['b']}\n\n"
            f"drop ur answer below 👇"
        )

    def _get_trending_summary(self) -> str:
        try:
            from content.trend_scanner import trend_scanner
            topics = trend_scanner.top_topics(n=5)
            cricket = trend_scanner.cricket_update()
            lines = ["*what's trending rn:*\n"]
            for i, t in enumerate(topics, 1):
                lines.append(f"{i}. {t[:80]}")
            lines.append(f"\n*cricket:* {cricket}")
            return "\n".join(lines)
        except Exception as e:
            return f"couldn't fetch trends: {e}"

    def _daily_briefing(self) -> str:
        """Compile full daily briefing: trends + ideas + analytics."""
        lines = ["*KenBot daily briefing*\n"]
        try:
            from content.trend_scanner import trend_scanner
            topics = trend_scanner.top_topics(n=3)
            lines.append("*top trends:*")
            for t in topics:
                lines.append(f"• {t[:70]}")
        except Exception:
            pass
        try:
            from content.idea_factory import idea_factory
            ideas = idea_factory.get_daily_ideas()
            lines.append("\n*today's post ideas:*")
            for t in ideas.get("tweet_ideas", [])[:3]:
                lines.append(f"• {t[:70]}")
        except Exception:
            pass
        try:
            from analytics.performance import analytics
            ts = analytics.twitter_summary()
            lines.append(f"\n*twitter:* {ts.get('total', 0)} posts | "
                         f"{ts.get('total_likes', 0)} likes | {ts.get('total_rt', 0)} RTs")
        except Exception:
            pass
        return "\n".join(lines)

    # ── Singleton ──────────────────────────────────────────────────────


# Singleton
ken_ai = KenAI()
