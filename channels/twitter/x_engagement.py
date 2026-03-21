"""
Ken ClawdBot — X Feed Scraper & Engagement Engine
Scrapes the For You feed, learns what's trending, likes/replies, and posts about
whatever the algorithm is pushing — not just a hardcoded topic list.
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

from config.settings import settings
from core.ai_engine import ken_ai
from memory.store import memory
from utils.logger import logger

SESSION_PATH   = Path(settings.root_dir) / "credentials" / "twitter_session.json"
ENGAGED_KEY    = "x_engaged_posts"       # post IDs we already acted on
LEARNED_KEY    = "x_learned_feed_topics" # AI-discovered topics from the feed
RECENT_TOPICS_KEY = "x_recent_post_topics"  # topics used recently — avoid repeating
MAX_LIKES_PER_RUN    = 5
MAX_REPLIES_PER_RUN  = 2
LEARNED_TOPICS_MAX   = 40  # keep last N discovered topics in memory
RECENT_TOPICS_MAX    = 20  # rolling window of recent post topics to remember
TOPIC_COOLDOWN_POSTS = 8   # don't reuse the same topic slug within this many posts

# ── Content pillar rotation — ensures variety across tweet categories ────────
# Each run picks the pillar that was used LEAST recently.
CONTENT_PILLARS = [
    "valorant_esports",
    "cricket_ipl",
    "f1_racing",
    "tech_ai_coding",
    "meme_internet",
    "bollywood_pop",
    "general_chaos",
]

# Per-pillar topic pools — cycling within a pillar also rotates sub-topics
PILLAR_TOPICS: dict[str, list[str]] = {
    "valorant_esports": [
        "TenZ", "Zekken", "Sacy", "Sentinels", "fns", "boaster", "tarik", "shanks",
        "yay", "nAts", "aspas", "Derke", "Demon1", "LOUD", "Fnatic", "NRG Valorant",
        "Karmine Corp", "VCT Champions", "Valorant ranked", "Valorant agent meta",
        "VCT Americas", "VCT EMEA", "VCT Pacific", "Valorant patch notes",
    ],
    "cricket_ipl": [
        "Kohli", "RCB", "Rohit Sharma", "Jasprit Bumrah", "IPL 2026",
        "India test cricket", "India vs Pakistan", "MS Dhoni legacy",
        "T20 World Cup", "Hardik Pandya", "Shubman Gill", "Yashasvi Jaiswal",
    ],
    "f1_racing": [
        "Max Verstappen", "Carlos Sainz", "Charles Leclerc", "Lewis Hamilton",
        "Ferrari 2026", "F1 qualifying drama", "F1 tyre strategy",
        "Red Bull Racing", "Lando Norris", "McLaren F1", "F1 Miami GP",
    ],
    "tech_ai_coding": [
        "vibe coding", "ChatGPT", "Claude AI", "cursor AI", "AI replacing devs",
        "debugging at 2am", "leetcode grind", "tech layoffs 2026", "software engineers",
        "AI agents", "startup culture", "open source", "python is life",
        "developer memes", "stackoverflow", "tech interviews",
    ],
    "meme_internet": [
        "twitter drama", "Indian meme", "reddit meme", "the algorithm",
        "going viral", "ratio", "chronically online", "main character energy",
        "parasocial", "brain rot content", "NPC energy", "rizz",
    ],
    "bollywood_pop": [
        "Bollywood 2026", "Netflix India", "Marvel 2026", "new anime drop",
        "Indian music", "Arijit Singh", "SRK", "Ranveer Singh energy",
    ],
    "general_chaos": [
        "Monday morning", "sleep", "food delivery", "traffic", "bangalore life",
        "Indian tech bro", "overthinking", "late night thoughts", "adulting is hard",
        "2am thoughts", "weekend vs monday", "chai supremacy",
    ],
}

# ── Topics to hunt for (likes + replies) ────────────────────────────────────
SEARCH_TOPICS = [
    # Gaming / Esports
    "TenZ Valorant",
    "Sentinels VCT",
    "Valorant patch",
    "Valorant ranked",
    # Cricket / Kohli
    "Virat Kohli",
    "RCB IPL",
    "India cricket",
    # F1
    "Max Verstappen F1",
    "Carlos Sainz F1",
    "Formula 1 race",
    # Tech / AI
    "AI news today",
    "ChatGPT OpenAI",
    "vibe coding",
    "software engineer meme",
    "tech layoffs",
    "cursor AI",
    # Pop culture / trending
    "viral twitter today",
    "what's trending twitter",
    "Netflix new show",
    "Bollywood",
    # Memes / internet culture
    "twitter meme today",
    "reddit meme",
    "Indian meme",
    # Gaming general
    "PC gaming",
    "game release 2026",
    # Coding / dev life
    "developer meme",
    "coding humor",
]

# Hype/glorification tweet templates — celebrating the greats + broad topics
SHITPOST_TEMPLATES = [
    # Glorification (for faves)
    "{topic} is literally built different and i will not be taking questions",
    "the way {topic} makes everything look effortless is actually criminal",
    "no thoughts just {topic} highlights on repeat",
    "people underestimate {topic} and then look embarrassed later. every time.",
    "{topic} said hold my drink and proceeded to rewrite history",
    "we do not deserve {topic} and that's the uncomfortable truth",
    "name a bigger clutch player than {topic}. go ahead. i'll wait.",
    # Tech / AI jokes
    "the {topic} hype is real and i am drinking the kool-aid unironically",
    "me: i'll sleep early\n{topic}: new update dropped\nme: ",
    "they said {topic} would replace us. it replaced most of my coworkers first.",
    # Internet / relatable
    "nobody:\nme at 2am: reading every thread about {topic} ever written",
    "getting into {topic} is genuinely a personality trait at this point",
    "the people who say {topic} isn't that important have never been humbled by {topic}",
    "explaining {topic} to my parents is my villain origin story",
    # Crack / absurd
    "{topic} in 2026 is just therapy with extra steps",
    "my roman empire: {topic}. posting about it again. goodnight.",
    "hot take: {topic} is the only thing holding society together",
    "imagine not caring about {topic}. wild life that must be.",
    "some days you wake up and realize {topic} is the only thing that makes sense",
    "the algorithm knows. it always shows me {topic} content at my lowest moments.",
]

SHITPOST_TOPICS = [
    # Faves to glorify
    "TenZ", "Zekken", "Sacy", "Sentinels",
    "fns", "boaster", "tarik", "shanks",
    "yay", "nAts", "aspas", "Derke", "Demon1",
    "LOUD", "Fnatic", "NRG Valorant", "Karmine Corp",
    "VCT", "Valorant Champions", "Valorant ranked",
    # Cricket / F1
    "Kohli", "RCB",
    "Max Verstappen", "Charles Leclerc", "F1",
    # Tech / AI
    "AI taking over", "software engineers", "ChatGPT", "vibe coding",
    "debugging at 2am", "leetcode", "tech startups",
    # Memes / internet
    "twitter drama", "going viral", "the algorithm",
    "Indian tech bro", "bangalore life",
    # Pop culture
    "Netflix", "Bollywood", "Marvel", "DC",
    # General chaos
    "Monday morning", "sleep", "food delivery", "traffic",
]


class XEngagement:
    """
    Playwright-based engagement: scrape For You feed → learn topics → like → reply → tweet.
    The bot learns what the algorithm is pushing and adapts its content accordingly.
    """

    def __init__(self) -> None:
        self._engaged: set[str] = self._load_engaged()

    # ── Persistent state ──────────────────────────────────────────────────

    def _load_engaged(self) -> set[str]:
        try:
            raw = memory.get(ENGAGED_KEY, "")
            return set(json.loads(raw)) if raw else set()
        except Exception:
            return set()

    def _save_engaged(self) -> None:
        trimmed = list(self._engaged)[-500:]
        memory.set(ENGAGED_KEY, json.dumps(trimmed))

    # ── Feed learning ──────────────────────────────────────────────────

    def _learn_from_feed(self, posts: list[dict]) -> list[str]:
        """
        After scraping the For You feed:
        1. Ask AI what topics are trending (stored for shitpost + tweet generation)
        2. Tag each post dict with a detected topic string in-place
           (used downstream to filter reply targets + pass topic to _generate_reply)
        Returns list of discovered topic strings.
        """
        if not posts:
            return []
        texts = [p["text"] for p in posts if p.get("text")]
        if not texts:
            return []

        feed_snapshot = "\n".join(f"- {t[:160]}" for t in texts[:20])

        # ── Step 1: batch topic discovery (for shitpost/tweet prompts) ──────
        discovered: list[str] = []
        try:
            system = (
                "You are an analyst reading a Twitter/X For You feed. "
                "Extract the main topics, people, events, memes, or conversations "
                "that are trending in this snapshot. Be specific — not 'tech' but "
                "'cursor AI vibe coding', not 'sports' but 'TenZ ace clip'. "
                "Return ONLY a JSON array of 5-10 short topic strings (max 6 words each)."
            )
            prompt = f"For You feed right now:\n{feed_snapshot}\n\nReturn JSON array of trending topics:"
            raw = ken_ai._call(system, prompt, model="claude-haiku-4-5", max_tokens=200, use_cache=False)
            raw = raw.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
            discovered = [str(t).strip() for t in json.loads(raw) if t][:10]

            existing_raw = memory.get(LEARNED_KEY, "[]")
            try:
                existing: list[str] = json.loads(existing_raw)
            except Exception:
                existing = []
            merged = discovered + [t for t in existing if t not in discovered]
            memory.set(LEARNED_KEY, json.dumps(merged[:LEARNED_TOPICS_MAX]))
            logger.info(f"Feed learned {len(discovered)} new topics: {discovered[:5]}")
        except Exception as exc:
            logger.debug(f"Feed topic discovery failed: {exc}")

        # ── Step 2: per-post topic tagging (used for reply targeting) ────────
        # One batch AI call tags all posts at once → no extra latency per reply
        try:
            indexed = [(i, p) for i, p in enumerate(posts) if p.get("text")]
            if indexed:
                batch = "\n".join(f'{i}: "{p["text"][:120]}"' for i, p in indexed)
                tag_system = (
                    "Tag each post with ONE short topic category (2-4 words max). "
                    "Examples: 'valorant vct', 'football arsenal', 'cricket ipl', "
                    "'f1 race', 'tech ai', 'coding meme', 'bollywood', 'crypto', "
                    "'basketball nba', 'general meme'. "
                    "Return ONLY a JSON object mapping index string → topic string."
                )
                tag_prompt = f"Posts:\n{batch}\n\nReturn JSON object:"
                tag_raw = ken_ai._call(tag_system, tag_prompt, model="claude-haiku-4-5", max_tokens=300, use_cache=False)
                tag_raw = tag_raw.strip()
                if tag_raw.startswith("```"):
                    tag_raw = "\n".join(tag_raw.split("\n")[1:]).rstrip("`").strip()
                tags: dict = json.loads(tag_raw)
                for i, post in indexed:
                    post["topic"] = str(tags.get(str(i), "general")).lower().strip()
                logger.debug(f"Per-post topics tagged: {[p.get('topic','?') for p in posts[:6]]}")
        except Exception as exc:
            logger.debug(f"Per-post topic tagging failed: {exc}")
            # Fall back — posts without topic field will use "general"

        return discovered

    def _get_learned_topics(self) -> list[str]:
        """Return AI-discovered topics from recent For You feeds."""
        try:
            raw = memory.get(LEARNED_KEY, "[]")
            return json.loads(raw)
        except Exception:
            return []

    def get_feed_context_block(self) -> str:
        """
        Returns a short text block describing what's currently trending
        in the feed, for injection into AI prompts.
        """
        topics = self._get_learned_topics()
        if not topics:
            return ""
        top = topics[:12]
        return (
            "WHAT'S ACTUALLY TRENDING IN THE FOR YOU FEED RIGHT NOW:\n"
            + "\n".join(f"  - {t}" for t in top)
            + "\nUse these to inform your content — react to what's in the air."
        )

    def _build_browser(self, pw):
        browser = pw.chromium.launch(
            headless=True,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--no-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--window-size=1280,900",
            ],
        )
        context = browser.new_context(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/122.0.0.0 Safari/537.36"
            ),
            viewport={"width": 1280, "height": 900},
            locale="en-US",
            timezone_id="Asia/Kolkata",
        )
        context.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins',   { get: () => [1, 2, 3] });
            Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
            window.chrome = { runtime: {} };
        """)
        if SESSION_PATH.exists():
            try:
                cookies = json.loads(SESSION_PATH.read_text())
                if cookies:
                    context.add_cookies(cookies)
            except Exception:
                pass
        return browser, context

    def _is_logged_in(self, page) -> bool:
        page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
        time.sleep(2)
        for sel in [
            '[data-testid="SideNav_NewTweet_Button"]',
            '[data-testid="tweetButtonInline"]',
            '[aria-label="Post"]',
            'a[href="/compose/tweet"]',
        ]:
            try:
                page.locator(sel).first.wait_for(state="visible", timeout=3000)
                return True
            except Exception:
                continue
        return False

    # ── Scrape posts from search ──────────────────────────────────────────────

    def scrape_search(self, query: str, page, max_posts: int = 10, viral_only: bool = False) -> list[dict]:
        """Scrape posts from X search for a given query.
        viral_only=True uses the Top (trending) tab to find high-engagement posts.
        """
        # Use Top tab for viral posts (for replies), Live tab for fresh posts (for likes)
        tab = "top" if viral_only else "live"
        url = f"https://x.com/search?q={query.replace(' ', '%20')}&f={tab}"
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(3)

        posts = []
        seen_ids: set[str] = set()

        # Scroll to load posts
        for _ in range(3):
            articles = page.locator('article[data-testid="tweet"]').all()
            for article in articles:
                try:
                    # Get tweet link (contains the ID)
                    link_el = article.locator('a[href*="/status/"]').first
                    href = link_el.get_attribute("href")
                    if not href:
                        continue
                    tweet_id = href.split("/status/")[-1].split("/")[0].split("?")[0]
                    if not tweet_id or tweet_id in seen_ids or tweet_id in self._engaged:
                        continue
                    seen_ids.add(tweet_id)

                    # Get text
                    try:
                        text = article.locator('[data-testid="tweetText"]').first.inner_text(timeout=2000)
                    except Exception:
                        text = ""

                    # Get author handle
                    try:
                        author_el = article.locator('[data-testid="User-Name"] a').last
                        author_href = author_el.get_attribute("href") or ""
                        author = author_href.lstrip("/").split("/")[0]
                    except Exception:
                        author = ""

                    # Try to grab like count for viral sorting
                    likes = 0
                    try:
                        like_count_el = article.locator('[data-testid="like"] span').last
                        raw_count = like_count_el.inner_text(timeout=1500).strip().replace(",", "")
                        if raw_count:
                            if "K" in raw_count:
                                likes = int(float(raw_count.replace("K", "")) * 1000)
                            else:
                                likes = int(raw_count)
                    except Exception:
                        likes = 0

                    posts.append({
                        "id":     tweet_id,
                        "text":   text,
                        "author": author,
                        "url":    f"https://x.com{href}",
                        "el":     article,
                        "likes":  likes,
                    })

                    if len(posts) >= max_posts:
                        break
                except Exception:
                    continue

            if len(posts) >= max_posts:
                break
            page.evaluate("window.scrollBy(0, 800)")
            time.sleep(1.5)

        logger.info(f"Scraped {len(posts)} posts for: {query}")
        return posts

    # ── Scrape the For You home feed ─────────────────────────────────────────

    def scrape_for_you_feed(self, page, max_posts: int = 25) -> list[dict]:
        """
        Scrape posts from the X For You home timeline (live feed the algorithm pushes).
        Assumes _is_logged_in() was already called (page is already on x.com/home).
        Returns list of dicts: {id, text, author, url, el, likes}
        """
        # Make sure we're on home; click the "For you" tab if it's present
        try:
            for_you = page.locator('[role="tab"]:has-text("For you")').first
            for_you.wait_for(state="visible", timeout=5000)
            for_you.click()
            time.sleep(2)
        except Exception:
            # Tab not found or already selected — just proceed
            pass

        posts: list[dict] = []
        seen_ids: set[str] = set()

        for scroll_pass in range(6):  # up to 6 scroll passes to gather max_posts
            articles = page.locator('article[data-testid="tweet"]').all()
            for article in articles:
                try:
                    # Tweet ID from the status URL embedded in the article
                    link_el = article.locator('a[href*="/status/"]').first
                    href = link_el.get_attribute("href")
                    if not href:
                        continue
                    tweet_id = href.split("/status/")[-1].split("/")[0].split("?")[0]
                    if not tweet_id or tweet_id in seen_ids or tweet_id in self._engaged:
                        continue
                    seen_ids.add(tweet_id)

                    # Tweet text
                    try:
                        text = article.locator('[data-testid="tweetText"]').first.inner_text(timeout=2000)
                    except Exception:
                        text = ""

                    # Author handle
                    try:
                        author_href = article.locator('[data-testid="User-Name"] a').last.get_attribute("href") or ""
                        author = author_href.lstrip("/").split("/")[0]
                    except Exception:
                        author = ""

                    # Like count
                    likes = 0
                    try:
                        raw = article.locator('[data-testid="like"] span').last.inner_text(timeout=1500).strip()
                        raw = raw.replace(",", "")
                        if raw:
                            likes = int(float(raw.replace("K", "")) * 1000) if "K" in raw else int(raw)
                    except Exception:
                        likes = 0

                    posts.append({
                        "id":     tweet_id,
                        "text":   text,
                        "author": author,
                        "url":    f"https://x.com{href}",
                        "el":     article,
                        "likes":  likes,
                    })

                    if len(posts) >= max_posts:
                        break
                except Exception:
                    continue

            if len(posts) >= max_posts:
                break
            page.evaluate("window.scrollBy(0, 900)")
            time.sleep(random.uniform(1.5, 2.5))

        logger.info(f"For You feed scraped: {len(posts)} posts")
        return posts

    # ── Like a post ───────────────────────────────────────────────────────────

    def _like_post(self, article, tweet_id: str) -> bool:
        try:
            like_btn = article.locator('[data-testid="like"]').first
            like_btn.wait_for(state="visible", timeout=4000)
            like_btn.click()
            time.sleep(random.uniform(0.8, 1.5))
            logger.info(f"Liked tweet: {tweet_id}")
            return True
        except Exception as e:
            logger.debug(f"Like failed for {tweet_id}: {e}")
            return False

    # ── Reply to a post ───────────────────────────────────────────────────────

    def _reply_to_post(self, page, tweet_id: str, text: str, author: str, reply_text: str, tweet_url: str = "") -> bool:
        """
        Navigate directly to the tweet URL before replying.
        This avoids stale Playwright element references caused by page scrolls
        that happen during the learning/AI calls between scraping and replying.
        """
        try:
            # Go directly to the tweet — guarantees we're on the right post
            url = tweet_url or f"https://x.com/{author}/status/{tweet_id}"
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            time.sleep(random.uniform(1.8, 2.8))

            # Click the reply button on the main (first) tweet on the detail page
            reply_btn = None
            for sel in [
                '[data-testid="reply"]',
                'article [data-testid="reply"]',
            ]:
                try:
                    el = page.locator(sel).first
                    el.wait_for(state="visible", timeout=5000)
                    reply_btn = el
                    break
                except Exception:
                    continue

            if not reply_btn:
                logger.debug(f"Reply button not found on tweet page: {tweet_id}")
                return False

            reply_btn.click()
            time.sleep(2)

            # Reply compose box appears in a modal
            compose = None
            for sel in [
                '[data-testid="tweetTextarea_0"]',
                '[role="dialog"] [data-testid="tweetTextarea_0"]',
                '[role="dialog"] [role="textbox"]',
            ]:
                try:
                    el = page.locator(sel).first
                    el.wait_for(state="visible", timeout=5000)
                    compose = el
                    break
                except Exception:
                    continue

            if not compose:
                logger.debug(f"Reply compose not found for {tweet_id}")
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

            compose.click()
            time.sleep(0.3)
            compose.fill(reply_text)
            time.sleep(random.uniform(0.8, 1.4))

            # Click Post / Reply button
            post_btn = None
            for btn_sel in [
                '[data-testid="tweetButton"]',
                '[data-testid="tweetButtonInline"]',
                'xpath=//button[@role="button" and .//span[text()="Reply"]]',
            ]:
                try:
                    el = page.locator(btn_sel).first
                    el.wait_for(state="visible", timeout=4000)
                    post_btn = el
                    break
                except Exception:
                    continue

            if not post_btn:
                page.keyboard.press("Escape")
                return False

            post_btn.click()
            time.sleep(random.uniform(2, 3))
            logger.info(f"Replied to @{author} ({tweet_id}): {reply_text[:60]}")
            return True
        except Exception as e:
            logger.debug(f"Reply failed for {tweet_id}: {e}")
            try:
                page.keyboard.press("Escape")
            except Exception:
                pass
            return False

    # ── Domain expertise block (topic-matched, not injected blindly) ─────────

    @staticmethod
    def _fetch_topic_context(topic: str) -> str:
        """
        Fetches current grounded facts about a topic from the soul engine.
        Injected into tweet/reply prompts so the bot never posts stale/wrong info.
        E.g. before tweeting about Man City → gets current form, standings, key players.
        Before replying about Linkin Park → knows Chester died 2017, new vocalist 2024, etc.
        """
        if not topic or topic.lower().strip() in ("general", "general meme", "meme", "internet", ""):
            return ""
        try:
            from core.soul_engine import soul as _soul
            return _soul.build_topic_context(topic)
        except Exception:
            return ""

    @staticmethod
    def _domain_block(topic: str) -> str:
        """
        Returns topic-specific knowledge snippet ONLY when the post matches.
        This prevents Valorant knowledge bleeding into football replies.
        """
        t = topic.lower()
        if any(k in t for k in ("valorant", "vct", "tenz", "sentinels", "zekken", "sacy", "fnatic valo",
                                 "boaster", "tarik", "nats", "aspas", "derke", "demon1", "esport")):
            return (
                "\nVALORANT EXPERTISE: Deep knowledge — follows VCT Americas/EMEA/Pacific, "
                "meta shifts, patch impact, roster moves, creator watchparty discourse. "
                "Treat role/team/status as dynamic (pros retire, switch teams, move to streaming). "
                "If uncertain, avoid hard claims and react to the post's current context. "
                "React like a genuine stan with actual scene knowledge.\n"
            )
        if any(k in t for k in ("cricket", "ipl", "kohli", "rcb", "bcci", "ind ", "india cricket",
                                 "virat", "rohit", "test match", "odi", "t20")):
            return (
                "\nCRICKET EXPERTISE: Kohli/RCB devotee. India cricket pride. "
                "Know current squads, Test rankings, IPL storylines. React with passion.\n"
            )
        if any(k in t for k in ("f1", "formula 1", "formula one", "verstappen", "sainz", "hamilton",
                                 "ferrari", "red bull racing", "grand prix", "qualifying", "gp ")):
            return (
                "\nF1 EXPERTISE: Max Verstappen + Carlos Sainz loyalist. Know team standings, "
                "race results, tyre strategy debates. React with genuine fan energy.\n"
            )
        if any(k in t for k in ("tech", "ai ", "openai", "claude", "gpt", "coding", "software",
                                 "developer", "cursor", "vibe cod", "startup", "python", "javascript")):
            return (
                "\nTECH EXPERTISE: Bangalore software engineer. Relatable dev humor, "
                "AI takes, vibe coding opinions, startup culture observations.\n"
            )
        if any(k in t for k in ("football", "soccer", "premier league", "champions league", "arsenal",
                                 "man city", "liverpool", "manchester", "chelsea", "real madrid",
                                 "barcelona", "fifa", "la liga")):
            return (
                "\nFOOTBALL: Casual observer — enjoy the sport, know the big clubs. "
                "React naturally to what's in the post, don't pretend deep expertise.\n"
            )
        # For everything else — no domain block, just use your voice
        return ""

    # ── Generate reply via AI ─────────────────────────────────────────────────

    def _generate_reply(self, text: str, author: str, post_topic: str = "general") -> str:
        """
        Generate a reply that's strictly on-topic, sounds genuinely human,
        and picks the most fitting style for the specific post.
        """
        import re as _re

        voice_ctx = ""
        try:
            from core.soul_engine import soul as _soul
            voice_ctx = _soul.get_voice_context()
        except Exception:
            pass

        domain = self._domain_block(post_topic)

        # Fetch current grounded facts about this specific topic
        # so the reply never says something factually embarrassing
        topic_facts = self._fetch_topic_context(post_topic)
        unified_ctx = ""
        try:
            from core.cross_platform_brain import cross_platform_brain as _brain
            unified_ctx = _brain.build_unified_context(post_topic, platform="twitter_reply")
        except Exception:
            pass

        try:
            system = f"""You're ghostwriting a reply tweet for an extremely-online person.

THEIR VOICE (HOW to write — NOT what to write about):
{voice_ctx if voice_ctx else 'young bangalore software engineer, massive esports/sports nerd, gen-z, always online'}
{domain}
{topic_facts}
{unified_ctx}
══ THE ONLY RULE THAT MATTERS ══
Reply to what this post is ACTUALLY about. Topic: {post_topic}.
Never pivot to a different subject.
Use the CURRENT FACTS above to make sure you don't say anything wrong.
If you're not sure of a fact, don't assert it — react to the vibe instead.

PICK whatever style fits this particular post best:
  quick reaction  → "okay this actually cooked", "lmaooo stop", "wait this is so real"
  hot take        → spicy angle or light counter (roast the *take*, never the person)
  quote+react     → pull a word/phrase from their post and spin it
  relate hard     → "this is literally me", "why does this keep happening"
  fan hype        → full stan energy when something great happened
  genuine q       → one real question sparked by the post
  absurd take     → surreal but still on-topic — unhinged in a funny way
  just vibes      → sometimes the best reply is four words and a lowercase laugh

GOOD REPLY ENERGY (real person, varied — not all the same opener):
  okay that one tap genuinely made me close my eyes
  this take is so wrong it came back around to being right
  the audacity of this being actually true
  why does this keep happening every single time
  fr nobody talks about this enough
  lmaooo the disrespect is astronomical
  wait they actually did that??
  this is NOT the outcome i prayed for
  silent >> loud every time
  that's genuinely unhinged and i respect it
  i have been saying this for months
  the way this just ruined my evening

BOT PATTERNS TO NEVER DO:
  ✗ "That's a great point!"
  ✗ Restating what they said back to them
  ✗ "As a [topic] fan, I think..."
  ✗ Starting with "I think" or "This is"
  ✗ Complimenting them before the actual take
  ✗ Generic hype with no specific detail from the post
  ✗ Starting with "nah" or "bro" — you've already used those too much today, pick something else

FORMAT:
- all lowercase (caps only for intentional shouting e.g. "LMAOOO")
- 5-160 chars — shorter can be funnier, leave room for the post to breathe
- no hashtags, no @mentions unless quoting their handle naturally
- raw, punchy — text-message energy, not a facebook status"""

            prompt = (
                f"Post by @{author}:\n{text}\n\n"
                "Best reply (pick the style that actually fits, be specific to THIS post):"
            )
            reply = ken_ai._call(system, prompt, model="claude-haiku-4-5", max_tokens=90, use_cache=False)
            # Strip any wrapper the AI adds
            reply = reply.strip().strip('"\'')
            reply = _re.sub(r'^(reply[:\-]?\s*|option\s*\d+[:\-]?\s*)', '', reply, flags=_re.IGNORECASE)
            reply = _re.sub(r'(?im)^\s*(post by\s*@[^\n:]*:|original tweet:|best reply.*:|write your reply:|reply:)\s*', '', reply)
            reply = _re.sub(r'(?im)^\s*@[\w_]+\s*\n\s*post by\s*@', '@', reply)
            reply = _re.split(r'(?i)\bor if you want\b', reply)[0]
            reply = _re.split(r'(?i)\balternative\s*[:\-]?', reply)[0]
            reply = _re.sub(r'\n{2,}', '\n', reply).strip()
            try:
                from core.cross_platform_brain import cross_platform_brain as _brain
                reply = _brain.sanitize_social_text(reply, max_chars=200)
            except Exception:
                pass
            return reply.strip()[:200]
        except Exception as e:
            logger.debug(f"Reply gen failed: {e}")
            return ""

    # ── Main engagement run ───────────────────────────────────────────────────

    def run_engagement(self, topics: Optional[list[str]] = None) -> dict:
        """
        Main entry point.
        1. Opens For You feed — scrapes fresh posts X is pushing
        2. Likes posts from the feed
        3. Replies to the highest-engagement posts in the feed as comments
        topics param is ignored — we use the live For You feed now.
        Returns summary dict.
        """
        if not SESSION_PATH.exists():
            logger.warning("No Twitter session found — run _import_twitter_cookies.py first")
            return {"liked": 0, "replied": 0, "error": "no_session"}

        liked_count   = 0
        replied_count = 0

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed")
            return {"liked": 0, "replied": 0, "error": "no_playwright"}

        with sync_playwright() as pw:
            browser, context = self._build_browser(pw)
            page = context.new_page()

            if not self._is_logged_in(page):
                logger.error("Not logged in — session may have expired. Re-run _import_twitter_cookies.py")
                browser.close()
                return {"liked": 0, "replied": 0, "error": "not_logged_in"}

            # Scrape the For You feed — fresh, trending posts X pushes to us
            feed_posts = self.scrape_for_you_feed(page, max_posts=25)

            if not feed_posts:
                logger.warning("For You feed returned no posts")
                browser.close()
                return {"liked": 0, "replied": 0, "error": "empty_feed"}

            # Learn what's trending from this batch of feed posts
            self._learn_from_feed(feed_posts)

            # Sort by likes descending — find the viral ones to comment on
            viral_posts = sorted(feed_posts, key=lambda p: p["likes"], reverse=True)

            # Like first N posts from feed (random order for human feel)
            like_queue = [p for p in feed_posts if p["likes"] < 50000]  # skip mega-viral, focus mid-tier
            random.shuffle(like_queue)

            for post in like_queue:
                if liked_count >= MAX_LIKES_PER_RUN:
                    break
                if self._like_post(post["el"], post["id"]):
                    liked_count += 1
                    self._engaged.add(post["id"])
                    # Soul learning: record this liked post WITH its detected topic
                    try:
                        from core.soul_engine import soul as _soul
                        tag = post.get("topic", "")
                        text_with_topic = f"[{tag}] {post.get('text', '')}" if tag else post.get("text", "")
                        _soul.learn_from_x_like(text_with_topic, post.get("author", ""), post.get("likes", 0))
                    except Exception:
                        pass
                time.sleep(random.uniform(1.5, 3))

            # Reply to the most viral post we haven't touched
            # Build interest keywords dynamically from the soul's live topic web
            # — grows as Kenneth reveals more preferences (Man City, Linkin Park, etc.)
            _base_keywords = (
                "valorant", "vct", "tenz", "sentinels", "esport",
                "cricket", "ipl", "kohli", "rcb", "india cricket",
                "f1", "formula", "verstappen", "sainz",
                "tech", "ai ", "coding", "software", "developer", "startup",
                "football", "soccer", "premier league", "champions league",
                "gaming", "game", "bollywood", "meme", "funny", "humour",
                "linkin park", "man city", "manchester city",  # known preferences
            )
            # Pull additional keywords from the expanded interest web
            _web_keywords: tuple[str, ...] = ()
            try:
                from core.soul_engine import soul as _soul
                dynamic = _soul.get_dynamic_topics()
                # Convert topics into lowercase short slugs for keyword matching
                _web_keywords = tuple(t.lower()[:30] for t in dynamic[:40])
            except Exception:
                pass
            KEN_INTEREST_KEYWORDS = _base_keywords + _web_keywords
            for post in viral_posts:
                if replied_count >= MAX_REPLIES_PER_RUN:
                    break
                if post["id"] in self._engaged or not post["text"]:
                    continue
                if post["likes"] < 100 and len(viral_posts) >= 5:
                    continue

                post_topic = post.get("topic", "general")
                post_text_lower = post["text"].lower()

                # Skip posts on topics we have nothing to add to
                topic_match = any(
                    k in post_topic or k in post_text_lower
                    for k in KEN_INTEREST_KEYWORDS
                )
                if not topic_match:
                    logger.debug(f"Skipping off-topic post [{post_topic}]: {post['text'][:60]}")
                    continue

                reply_text = self._generate_reply(post["text"], post["author"], post_topic)
                if reply_text:
                    # Pass the tweet URL to navigate directly — avoids stale element refs
                    if self._reply_to_post(page, post["id"], post["text"], post["author"], reply_text, post["url"]):
                        replied_count += 1
                        self._engaged.add(post["id"])
                        # Soul learning: record this reply
                        try:
                            from core.soul_engine import soul as _soul
                            _soul.learn_from_x_reply(post["text"], reply_text, post["author"])
                        except Exception:
                            pass
                        try:
                            from core.cross_platform_brain import cross_platform_brain as _brain
                            _brain.record_topic("twitter", post_topic or post.get("topic", ""), source="x_reply")
                        except Exception:
                            pass
                    time.sleep(random.uniform(3, 5))

            # Save updated session
            try:
                SESSION_PATH.write_text(json.dumps(context.cookies()))
            except Exception:
                pass
            browser.close()

        self._save_engaged()
        logger.info(f"Engagement run done — liked: {liked_count}, replied: {replied_count}")
        return {"liked": liked_count, "replied": replied_count}

    # ── Shitpost generator ────────────────────────────────────────────────────

    def generate_shitpost(self, topic: Optional[str] = None) -> str:
        """Generate a hype/joke/crack tweet.
        Uses content pillar rotation to guarantee variety across categories.
        Tracks recently used topics and actively avoids repeating them.
        """
        self._last_shitpost_topic = None
        chosen_pillar = ""

        if topic is None:
            # Pull the full live topic web: feed topics + interest expansion + commands
            try:
                from core.soul_engine import soul as _soul
                all_topics = _soul.get_dynamic_topics()
            except Exception:
                all_topics = []

            used_slugs = self._recently_used_slugs()

            # Split into fresh feed-learned vs. everything else
            learned = self._get_learned_topics()
            fresh_learned = [t for t in learned if t.lower()[:50] not in used_slugs]

            # Fresh interest-web topics (not feed, not recently used)
            fresh_web = [t for t in all_topics if t.lower()[:50] not in used_slugs
                         and t not in learned][:30]

            if fresh_learned and random.random() < 0.45:
                # Feed-trending topic (most timely)
                topic = random.choice(fresh_learned[:12])
                chosen_pillar = "feed_learned"
                logger.debug(f"Shitpost using fresh feed topic: {topic}")
            elif fresh_web and random.random() < 0.55:
                # Soul interest web (personalised expansion)
                topic = random.choice(fresh_web[:20])
                chosen_pillar = "interest_web"
                logger.debug(f"Shitpost using interest web: {topic}")
            else:
                # Fall back to content pillar rotation
                chosen_pillar = self._pick_next_pillar()
                pool = PILLAR_TOPICS.get(chosen_pillar, SHITPOST_TOPICS)
                fresh_pool = [t for t in pool if t.lower()[:50] not in used_slugs]
                if not fresh_pool:
                    fresh_pool = pool
                topic = random.choice(fresh_pool)
                logger.debug(f"Shitpost pillar={chosen_pillar} topic={topic}")

        self._last_shitpost_topic = topic

        # ── Fetch current grounded facts about this topic before writing ──────────
        # This prevents the bot from tweeting stale or wrong info and getting trolled
        topic_facts = self._fetch_topic_context(topic)

        # Build what-was-recently-posted context so AI avoids those angles
        recent = self._load_recent_topics()
        recent_display = ", ".join(e["topic"] for e in recent[-6:]) if recent else "none"

        feed_ctx = self.get_feed_context_block()
        soul_ctx = ""
        try:
            from core.soul_engine import soul as _soul
            soul_ctx = _soul.get_soul_context("twitter")
        except Exception:
            pass

        try:
            system = (
                "You write viral tweets. Rules:\n"
                "- max 260 chars\n"
                "- lowercase only, extremely online gen-z energy\n"
                "- NO personal info — no real names, locations, job, school, relationships\n"
                "- 1-2 hashtags that real people actually search — put them at the END\n"
                "- VARY the format: hype tweets, crack jokes, memes, hot takes, shower thoughts, "
                "absurd observations, relatable humor, stan energy, chaotic takes, unpopular opinions\n"
                "- For any beloved player/team: glorify skill, clutch moments, legacy. Never mock them.\n"
                "- must feel like a real person tweeting at 1am, not a brand or bot\n"
                "- punchy, specific, quotable — something people actually retweet\n"
                "- VARY your openers — do NOT start with 'nah' or 'bro' every tweet. "
                "Use different entry points: the topic itself, a number, a reaction word, a question, "
                "an observation, a comparison, absurdist imagery, etc.\n"
                f"\n⚠ RECENTLY POSTED ABOUT (DO NOT repeat these angles or topics):\n  {recent_display}\n"
                "  Write something genuinely different — new angle, different aspect, fresh take.\n"
                + (f"\n{topic_facts}\n" if topic_facts else "")
                + (f"\n{feed_ctx}" if feed_ctx else "")
                + (f"\n{soul_ctx}" if soul_ctx else "")
            )
            prompt = (
                f"Write ONE tweet about: {topic}\n"
                "Pick a format you haven't used recently. Be specific, not generic.\n"
                "Output ONLY the raw tweet text. No labels, no quotes."
            )
            tweet = ken_ai._call(system, prompt, model="claude-haiku-4-5", max_tokens=110, use_cache=False)
            import re as _re
            tweet = _re.sub(r'^(option\s*\d+[:\-]?\s*|tweet[:\-]?\s*)', '', tweet.strip(), flags=_re.IGNORECASE)
            tweet = tweet.strip('"\' \n')
            # Mark pillar used (so next call rotates away from it)
            self._mark_topic_used(topic, chosen_pillar)
            return tweet[:260]
        except Exception:
            tmpl = random.choice(SHITPOST_TEMPLATES)
            self._mark_topic_used(topic, chosen_pillar)
            return tmpl.format(topic=topic)

    def post_shitpost(self, topic: Optional[str] = None) -> Optional[str]:
        """Generate and post a hype tweet. Returns tweet ID or 'browser_post_ok'."""
        from channels.twitter.poster import twitter
        tweet = self.generate_shitpost(topic)
        if not tweet:
            return None
        logger.info(f"Posting hype tweet: {tweet[:80]}")
        result = twitter.post_tweet(tweet)
        # Mark the topic used so next post avoids it
        if result and hasattr(self, '_last_shitpost_topic') and self._last_shitpost_topic:
            self._mark_topic_used(self._last_shitpost_topic)
        return result

    # ── Topic variety tracking ────────────────────────────────────────────────

    def _load_recent_topics(self) -> list[dict]:
        """Load recently used post topics (list of {slug, ts, pillar})."""
        try:
            raw = memory.get(RECENT_TOPICS_KEY, "[]")
            return json.loads(raw)
        except Exception:
            return []

    def _mark_topic_used(self, topic: str, pillar: str = "") -> None:
        """Record a topic as used. Keeps rolling window of RECENT_TOPICS_MAX entries."""
        recent = self._load_recent_topics()
        recent.append({
            "slug":   topic.lower()[:50],
            "topic":  topic,
            "pillar": pillar,
            "ts":     datetime.utcnow().isoformat(),
        })
        recent = recent[-RECENT_TOPICS_MAX:]
        memory.set(RECENT_TOPICS_KEY, json.dumps(recent))

    def _recently_used_slugs(self) -> set[str]:
        """Return set of topic slugs used in the last TOPIC_COOLDOWN_POSTS posts."""
        recent = self._load_recent_topics()
        window = recent[-TOPIC_COOLDOWN_POSTS:]
        return {e["slug"] for e in window}

    def _last_used_pillar(self) -> str:
        """Return the pillar used most recently (to avoid repeating it)."""
        recent = self._load_recent_topics()
        for entry in reversed(recent):
            if entry.get("pillar"):
                return entry["pillar"]
        return ""

    def _pick_next_pillar(self) -> str:
        """
        Pick the content pillar that has been used LEAST recently,
        or least frequently — guarantees variety across categories.
        """
        recent = self._load_recent_topics()
        # Count how recently each pillar was used (lower index = more recent)
        recency: dict[str, int] = {p: 999 for p in CONTENT_PILLARS}
        for i, entry in enumerate(reversed(recent[-20:])):
            p = entry.get("pillar", "")
            if p in recency and recency[p] == 999:
                recency[p] = i  # lower = more recent
        # Pick pillar with highest recency score (least recently used)
        last = self._last_used_pillar()
        candidates = sorted(CONTENT_PILLARS, key=lambda p: recency[p], reverse=True)
        # Never pick the same pillar twice in a row
        for p in candidates:
            if p != last:
                return p
        return candidates[0]


# Singleton
x_engagement = XEngagement()
