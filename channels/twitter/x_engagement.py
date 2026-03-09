"""
Ken ClawdBot — X Feed Scraper & Engagement Engine
Scrapes the For You feed, learns what's trending, likes/replies, and posts about
whatever the algorithm is pushing — not just a hardcoded topic list.
"""
from __future__ import annotations

import json
import random
import time
from pathlib import Path
from typing import Optional

from config.settings import settings
from core.ai_engine import ken_ai
from memory.store import memory
from utils.logger import logger

SESSION_PATH   = Path(settings.root_dir) / "credentials" / "twitter_session.json"
ENGAGED_KEY    = "x_engaged_posts"       # post IDs we already acted on
LEARNED_KEY    = "x_learned_feed_topics" # AI-discovered topics from the feed
MAX_LIKES_PER_RUN    = 5
MAX_REPLIES_PER_RUN  = 2
LEARNED_TOPICS_MAX   = 40  # keep last N discovered topics in memory

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
    "they said {topic} would replace us. bro replaced most of my coworkers first.",
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
        After scraping the For You feed, ask AI what topics are actually trending
        in those post texts. Persist to memory so future tweets can reference them.
        Returns list of discovered topic strings.
        """
        if not posts:
            return []
        # Build a condensed snapshot of what the feed looks like right now
        texts = [p["text"] for p in posts if p.get("text")]
        if not texts:
            return []
        feed_snapshot = "\n".join(f"- {t[:160]}" for t in texts[:20])
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
            # Parse JSON array
            raw = raw.strip()
            if raw.startswith("```"):
                raw = "\n".join(raw.split("\n")[1:]).rstrip("`").strip()
            discovered: list[str] = json.loads(raw)
            if not isinstance(discovered, list):
                return []
            discovered = [str(t).strip() for t in discovered if t][:10]

            # Merge with existing learned topics, keep freshest
            existing_raw = memory.get(LEARNED_KEY, "[]")
            try:
                existing: list[str] = json.loads(existing_raw)
            except Exception:
                existing = []
            # Prepend new (most recent first), dedup, cap at LEARNED_TOPICS_MAX
            merged = discovered + [t for t in existing if t not in discovered]
            merged = merged[:LEARNED_TOPICS_MAX]
            memory.set(LEARNED_KEY, json.dumps(merged))
            logger.info(f"Feed learned {len(discovered)} new topics: {discovered[:5]}")
            return discovered
        except Exception as exc:
            logger.debug(f"Feed learning failed: {exc}")
            return []

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

    def _reply_to_post(self, page, article, tweet_id: str, text: str, author: str, reply_text: str) -> bool:
        try:
            reply_btn = article.locator('[data-testid="reply"]').first
            reply_btn.wait_for(state="visible", timeout=4000)
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
                # Close modal if open
                try:
                    page.keyboard.press("Escape")
                except Exception:
                    pass
                return False

            compose.click()
            time.sleep(0.3)
            compose.fill(reply_text)
            time.sleep(random.uniform(0.8, 1.2))

            # Click Post button
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

    # ── Generate reply via AI ─────────────────────────────────────────────────

    def _generate_reply(self, text: str, author: str) -> str:
        """Generate a viral-friendly reply, informed by what's trending in the feed."""
        feed_ctx = self.get_feed_context_block()
        try:
            system = (
                "You write witty replies to posts on X. Rules:\n"
                "- max 200 chars\n"
                "- lowercase, gen-z, very online energy\n"
                "- NO personal info — no real names, city, job, school, relationships\n"
                "- no hashtags\n"
                "- can be: hot take, funny observation, passionate stan reply, hype, roast the take (not person)\n"
                "- Valorant knowledge: stan TenZ/Sentinels/Zekken/Sacy. Respect fns (best IGL brain). "
                "Love boaster's energy. Follow tarik. Rate shanks, yay, nAts, aspas, Derke, Demon1. "
                "Know VCT Americas/EMEA/Pacific, team rosters, meta, agent picks, patch changes.\n"
                "- Cricket: Kohli/RCB stan. India cricket pride.\n"
                "- F1: Max Verstappen + Carlos Sainz loyalist.\n"
                "- Tech/AI/dev: relatable software engineer humor, AI takes, vibe coding opinions.\n"
                "- If post is about any of your topics: go full knowledgeable stan mode with specific context\n"
                "- If unrelated: be funny/observational, add something to the conversation\n"
                "- sound like a real extremely-online person with actual knowledge, not a bot\n"
                + (f"\n{feed_ctx}" if feed_ctx else "")
            )
            prompt = f"Post by @{author}: {text}\n\nYour reply (max 200 chars):"
            reply = ken_ai._call(system, prompt, model="claude-haiku-4-5", max_tokens=80, use_cache=False)
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
                time.sleep(random.uniform(1.5, 3))

            # Reply to the most viral post we haven't touched
            for post in viral_posts:
                if replied_count >= MAX_REPLIES_PER_RUN:
                    break
                if post["id"] in self._engaged or not post["text"]:
                    continue
                # Target posts with real engagement — our reply gets visibility
                if post["likes"] >= 100 or len(viral_posts) < 5:
                    reply_text = self._generate_reply(post["text"], post["author"])
                    if reply_text:
                        if self._reply_to_post(page, post["el"], post["id"], post["text"], post["author"], reply_text):
                            replied_count += 1
                            self._engaged.add(post["id"])
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
        60 % of the time picks a topic the algorithm is actually pushing right now.
        40 % falls back to the hardcoded SHITPOST_TOPICS roster.
        """
        if topic is None:
            learned = self._get_learned_topics()
            if learned and random.random() < 0.60:
                topic = random.choice(learned)
                logger.debug(f"Shitpost using feed-learned topic: {topic}")
            else:
                topic = random.choice(SHITPOST_TOPICS)
        feed_ctx = self.get_feed_context_block()
        try:
            system = (
                "You write viral tweets. Rules:\n"
                "- max 260 chars\n"
                "- lowercase only, extremely online gen-z energy\n"
                "- NO personal info — no real names, locations, job, school, relationships\n"
                "- 1-2 hashtags that real people actually search (e.g. #Valorant #VCT #TenZ #Cricket #Kohli #F1 #AI #Coding #IndianTwitter #Memes) — put them at the END\n"
                "- VARY the format: hype tweets, crack jokes, memes, hot takes, shower thoughts, "
                "absurd observations, relatable dev/tech humor, stan energy, chaotic takes\n"
                "- Valorant: deep knowledge — TenZ/Sentinels/Zekken/Sacy are home team. fns = best IGL, "
                "boaster = chaotic energy king, tarik = content goat, shanks/yay/nAts/aspas/Derke/Demon1 "
                "all deserve flowers. Know teams: LOUD/Fnatic/NRG/Liquid/PRX/Karmine. "
                "Can post about any of them — don't milk only TenZ. Cover the whole scene.\n"
                "- For any loved player/team: glorify skill, clutch moments, legacy, hype them up. Never mock them.\n"
                "- For tech/AI/coding/internet topics: funny, observational, relatable, or unhinged\n"
                "- For trending/pop culture: hot take or funny reaction\n"
                "- Crack jokes are welcome. Dark-ish humor OK if not targeting real people\n"
                "- voice: bangalore software engineer who is a massive esports/sports nerd, extremely online\n"
                "- must feel like a real person tweeting at 1am, not a brand or bot\n"
                "- punchy, specific, quotable — make it feel like something real people would retweet"
                + (f"\n\n{feed_ctx}" if feed_ctx else "")
            )
            prompt = f"Write a tweet about: {topic}"
            tweet = ken_ai._call(system, prompt, model="claude-haiku-4-5", max_tokens=100, use_cache=False)
            return tweet.strip()[:260]
        except Exception:
            tmpl = random.choice(SHITPOST_TEMPLATES)
            return tmpl.format(topic=topic)

    def post_shitpost(self, topic: Optional[str] = None) -> Optional[str]:
        """Generate and post a hype tweet. Returns tweet ID or 'browser_post_ok'."""
        from channels.twitter.poster import twitter
        tweet = self.generate_shitpost(topic)
        if not tweet:
            return None
        logger.info(f"Posting hype tweet: {tweet[:80]}")
        return twitter.post_tweet(tweet)


# Singleton
x_engagement = XEngagement()
