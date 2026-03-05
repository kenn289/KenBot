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
    ) -> str:
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

        style_block = ""
        style_summary = self._get_style_summary()
        if style_summary:
            style_block = f"\nLEARNED STYLE (adapt your replies to match these patterns — this is how he actually texts):\n{style_summary}\n"

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
{style_block}
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
        return self._call(system, prompt, model=model, max_tokens=max_tok)

    def generate_tweet(self, topic: str, style: str = "hot take") -> str:
        """
        Generate a single tweet (â‰¤280 chars) on a given topic.
        style options: 'hot take' | 'joke' | 'reaction' | 'thread_opener'
        """
        system = self._system_prompt(context=f"twitter_post_{style}")
        prompt = (
            f"Write ONE tweet about: {topic}\n"
            f"Style: {style}\n"
            "Include 1-3 relevant hashtags at the end. Keep it under 265 characters.\n"
            "Do NOT add quotation marks around the tweet. Just output the tweet text."
        )
        raw = self._call(system, prompt, model=MODEL_HAIKU, max_tokens=300, use_cache=False)
        # Ensure it fits
        from utils.helpers import truncate
        return truncate(raw, 280)

    def generate_tweet_thread(self, topic: str, num_tweets: int = 5) -> list[str]:
        """
        Generate a tweet thread (numbered 1/n ... n/n) on a topic.
        Returns list of tweet strings.
        """
        system = self._system_prompt(context="twitter_thread")
        prompt = (
            f"Write a {num_tweets}-tweet thread about: {topic}\n"
            "Format: return ONLY a JSON array of strings, one string per tweet, no extra text.\n"
            "Each tweet â‰¤265 characters. Add hashtags only on the last tweet.\n"
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
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            logger.warning("YT metadata JSON parse failed")
            return {"title": topic, "description": "", "tags": []}

    def generate_yt_script(self, topic: str, duration_minutes: int = 5) -> str:
        """
        Generate a YouTube video script.
        ~130 words/minute â†’ duration * 130 words target.
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
            "Consider: what's trending in gaming/esports/dc/marvel/football.\n"
            "Return ONLY JSON: {\"topic\": \"...\", \"angle\": \"...\", \"platform\": \"both|twitter|youtube\"}"
        )
        raw = self._call(system, prompt, model=MODEL_HAIKU, max_tokens=200, use_cache=False)
        try:
            return json.loads(raw)
        except Exception:
            return {"topic": "Valorant", "angle": "TenZ best plays", "platform": "both"}


# Singleton
ken_ai = KenAI()
