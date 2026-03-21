"""
KenBot OS — Reddit Engine
Posts insights, comments on trending posts, and answers questions
on Reddit to drive traffic to Kenneth's Twitter and YouTube.
"""
from __future__ import annotations

import json
import random
import re
import time
from pathlib import Path
from typing import Optional

from content.reddit_miner import reddit_miner, _HEADERS
from config.settings import settings
from memory.store import memory
from utils.logger import logger

_POST_LOG_KEY = "reddit_post_log"
_REDDIT_SESSION_PATH = Path(settings.root_dir) / "credentials" / "reddit_session.json"

# Subreddits where Ken can add value with short, genuine comments
_COMMENT_SUBS: dict[str, str] = {
    "valorant":        "gaming_esports",
    "learnprogramming": "tech_dev",
    "artificial":       "tech_ai",
    "Cricket":          "cricket",
    "bangalore":        "bangalore_local",
}

# Comment seed styles — short, genuine, non-promotional
_COMMENT_STYLES = [
    "honestly this is {adjective}. {extra}",
    "wait this is a much better take than most people are giving it credit for",
    "counter-point: {counter}",
    "been following this for a while and {observation}",
    "not wrong. the part about {topic} specifically is underrated.",
]


class RedditEngine:
    """
    Manages Reddit presence to build traffic and visibility.
    Supports automatic commenting when Reddit API credentials are configured.
    """

    def _reddit_ready(self) -> bool:
        return bool(
            settings.reddit_client_id
            and settings.reddit_client_secret
            and settings.reddit_username
            and settings.reddit_password
        )

    def _reddit_browser_ready(self) -> bool:
        return bool(
            (settings.reddit_username and settings.reddit_password)
            or _REDDIT_SESSION_PATH.exists()
        )

    @staticmethod
    def _is_rate_limited_error(exc: Exception) -> bool:
        msg = str(exc).lower()
        return (
            "ratelimit" in msg
            or "too many requests" in msg
            or "status code: 429" in msg
            or "http 429" in msg
        )

    def _reddit_client(self):
        if not self._reddit_ready():
            return None
        try:
            import praw
            return praw.Reddit(
                client_id=settings.reddit_client_id,
                client_secret=settings.reddit_client_secret,
                username=settings.reddit_username,
                password=settings.reddit_password,
                user_agent=settings.reddit_user_agent or "KenBot/1.0 by Kenneth",
            )
        except Exception as exc:
            logger.warning(f"Reddit client init failed: {exc}")
            return None

    @staticmethod
    def _post_id_from_url(url: str) -> str:
        m = re.search(r"/comments/([a-z0-9]+)/", url or "", flags=re.IGNORECASE)
        return m.group(1) if m else ""

    @staticmethod
    def _sanitize_comment(text: str) -> str:
        text = (text or "").strip().strip('"\'')
        text = re.sub(r'(?im)^\s*(reddit post title:|write your comment:|comment:)\s*', '', text)
        text = re.split(r'(?i)\bor if you want\b', text)[0]
        text = re.sub(r'\n{2,}', '\n', text).strip()
        return text[:300]

    @staticmethod
    def _is_confident_comment(text: str) -> bool:
        t = (text or "").strip().lower()
        if not t or len(t) < 20:
            return False

        uncertain_patterns = [
            "not sure",
            "i'm not sure",
            "im not sure",
            "i might be wrong",
            "could be wrong",
            "i think maybe",
            "maybe",
            "probably",
            "not certain",
            "can't confirm",
            "cannot confirm",
            "unsure",
            "hard to say",
            "idk",
            "i don't know",
            "dont know",
        ]
        if any(p in t for p in uncertain_patterns):
            return False

        # Avoid empty praise / low-value comments
        low_value = [
            "great post",
            "nice post",
            "well said",
            "interesting",
            "agreed",
        ]
        if any(p == t or t.startswith(p + ".") for p in low_value):
            return False

        return True

    def _save_reddit_session(self, cookies: list[dict]) -> None:
        try:
            _REDDIT_SESSION_PATH.parent.mkdir(parents=True, exist_ok=True)
            _REDDIT_SESSION_PATH.write_text(json.dumps(cookies), encoding="utf-8")
        except Exception:
            pass

    def _load_reddit_session(self) -> list[dict]:
        try:
            if _REDDIT_SESSION_PATH.exists():
                return json.loads(_REDDIT_SESSION_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
        return []

    def _reddit_login(self, page) -> bool:
        try:
            page.goto("https://www.reddit.com/login/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            user_ok = False
            for sel in ['input[name="username"]', '#loginUsername']:
                try:
                    el = page.locator(sel).first
                    el.wait_for(state="visible", timeout=4000)
                    el.fill(settings.reddit_username)
                    user_ok = True
                    break
                except Exception:
                    continue
            if not user_ok:
                return False

            pass_ok = False
            for sel in ['input[name="password"]', '#loginPassword']:
                try:
                    el = page.locator(sel).first
                    el.wait_for(state="visible", timeout=4000)
                    el.fill(settings.reddit_password)
                    pass_ok = True
                    break
                except Exception:
                    continue
            if not pass_ok:
                return False

            clicked = False
            for sel in ['button[type="submit"]', 'button:has-text("Log In")', 'button:has-text("Continue")']:
                try:
                    btn = page.locator(sel).first
                    btn.wait_for(state="visible", timeout=4000)
                    btn.click()
                    clicked = True
                    break
                except Exception:
                    continue
            if not clicked:
                page.keyboard.press("Enter")

            time.sleep(5)
            page.goto("https://www.reddit.com/", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)
            body = (page.content() or "").lower()
            if "log in" in body and "continue with" in body and "reddit" in body:
                return False
            return True
        except Exception:
            return False

    def _post_comment_via_browser(self, post_url: str, comment: str) -> Optional[str]:
        if not self._reddit_browser_ready():
            return None
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.warning("Playwright not installed for Reddit browser fallback")
            return None

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--no-sandbox",
                    "--disable-dev-shm-usage",
                ],
            )
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1400, "height": 900},
                locale="en-US",
            )

            cookies = self._load_reddit_session()
            if cookies:
                try:
                    context.add_cookies(cookies)
                except Exception:
                    pass

            page = context.new_page()
            try:
                # old.reddit has a simpler, stable comment form for automation
                old_url = re.sub(r"https?://(www\.)?reddit\.com", "https://old.reddit.com", post_url)
                page.goto(old_url, wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)

                html = (page.content() or "").lower()
                if "login" in page.url.lower() or ("log in" in html and "reddit" in html):
                    if not self._reddit_login(page):
                        browser.close()
                        return None
                    self._save_reddit_session(context.cookies())
                    page.goto(old_url, wait_until="domcontentloaded", timeout=30000)
                    time.sleep(2)

                compose = None
                for sel in [
                    'textarea[name="text"]',
                    'textarea[name="comment"]',
                    'textarea[placeholder*="thoughts"]',
                    'textarea[placeholder*="comment"]',
                    'div[contenteditable="true"]',
                ]:
                    try:
                        el = page.locator(sel).first
                        el.wait_for(state="visible", timeout=5000)
                        compose = el
                        break
                    except Exception:
                        continue
                if not compose:
                    browser.close()
                    return None

                compose.click()
                try:
                    compose.fill(comment)
                except Exception:
                    compose.type(comment, delay=10)
                time.sleep(1)

                post_btn = None
                for sel in [
                    'button[name="save"]',
                    'button:has-text("save")',
                    'button:has-text("Comment")',
                    'button[type="submit"]',
                ]:
                    try:
                        btn = page.locator(sel).first
                        btn.wait_for(state="visible", timeout=5000)
                        post_btn = btn
                        break
                    except Exception:
                        continue
                if not post_btn:
                    browser.close()
                    return None

                post_btn.click()
                time.sleep(3)
                self._save_reddit_session(context.cookies())
                browser.close()
                return "browser_comment_ok"
            except Exception as exc:
                logger.warning(f"Reddit browser fallback failed: {exc}")
                browser.close()
                return None

    def post_comment(self, post_url: str, comment: str) -> Optional[str]:
        """Post a comment to Reddit and return comment ID if successful."""
        post_id = self._post_id_from_url(post_url)
        if not post_id:
            logger.warning(f"Reddit post ID parse failed for URL: {post_url}")
            return None

        lock_key = f"reddit_commented:{post_id}"
        if memory.get(lock_key, ""):
            logger.info(f"Reddit post already commented: {post_id}")
            return None

        safe_comment = self._sanitize_comment(comment)
        try:
            from core.cross_platform_brain import cross_platform_brain as _brain
            safe_comment = _brain.sanitize_social_text(safe_comment, max_chars=300)
        except Exception:
            pass
        if not safe_comment:
            return None

        client = self._reddit_client()
        if client:
            try:
                submission = client.submission(id=post_id)
                result = submission.reply(safe_comment)
                comment_id = getattr(result, "id", "") or ""
                memory.set(lock_key, str(int(time.time())))
                logger.info(f"Reddit comment posted via API: {comment_id} on {post_id}")
                return comment_id or "ok"
            except Exception as exc:
                logger.warning(f"Reddit API comment failed: {exc}")
                if self._is_rate_limited_error(exc):
                    logger.info("Trying Reddit browser fallback due to API rate limit...")
                    browser_result = self._post_comment_via_browser(post_url, safe_comment)
                    if browser_result:
                        memory.set(lock_key, str(int(time.time())))
                        logger.info(f"Reddit comment posted via browser on {post_id}")
                        return browser_result
                return None

        # No API client configured — try browser mode directly
        if self._reddit_browser_ready():
            browser_result = self._post_comment_via_browser(post_url, safe_comment)
            if browser_result:
                memory.set(lock_key, str(int(time.time())))
                logger.info(f"Reddit comment posted via browser on {post_id}")
                return browser_result

        logger.warning("Reddit auto-post failed: neither API nor browser flow could post")
        return None

    def generate_comment(self, post_title: str, subreddit: str = "general") -> str:
        """
        Generate a short, genuine Reddit comment using Claude + live Tavily context.
        Reads the post, thinks about what's actually interesting, and responds as Kenneth.
        """
        try:
            from core.ai_engine import ken_ai
            from core.news_fetcher import news_fetcher as _nf
            from config.ken_personality import IDENTITY
            from core.soul_engine import soul as _soul

            # Pull live context so the comment is factually grounded
            live_ctx = ""
            try:
                live_ctx = _nf.get_news_context_for_claude(post_title)
            except Exception:
                pass

            ctx_block = ""
            if live_ctx:
                ctx_block = f"\n\nLIVE CONTEXT:\n{live_ctx}\nUse this to make your comment accurate and current."

            soul_ctx = ""
            try:
                soul_ctx = _soul.get_soul_context("general")
            except Exception:
                soul_ctx = ""

            topic_ctx = ""
            try:
                topic_ctx = _soul.build_topic_context(f"r/{subreddit} {post_title}"[:180])
            except Exception:
                topic_ctx = ""

            unified_ctx = ""
            try:
                from core.cross_platform_brain import cross_platform_brain as _brain
                unified_ctx = _brain.build_unified_context(post_title, platform="reddit")
            except Exception:
                unified_ctx = ""

            niche = _COMMENT_SUBS.get(subreddit, "general")
            system = (
                f"{IDENTITY}\n\n"
                f"You are commenting on a Reddit post in r/{subreddit} (topic: {niche}). "
                "Write a genuine, short comment — 1-3 sentences max. "
                "Add real value: a specific observation, a counter-point, or something the thread is missing. "
                "Sound like a person who actually knows this topic, not someone promoting themselves. "
                "Prefer CURRENT reality over old assumptions. "
                "Do not assert player roles, team affiliation, or status unless the live context supports it. "
                "Lowercase/casual but genuine. No fluff. No self-promotion. No 'great post!'.\n"
                "Output ONLY the comment text, nothing else."
                + (f"\n\nVOICE CONTEXT:\n{soul_ctx}" if soul_ctx else "")
                + (f"\n\nTOPIC CONTEXT:\n{topic_ctx}" if topic_ctx else "")
                + (f"\n\nCROSS-PLATFORM CONTEXT:\n{unified_ctx}" if unified_ctx else "")
                + ctx_block
            )
            comment = ken_ai._call(
                system,
                f"Reddit post title: {post_title}\n\nWrite your comment:",
                model="claude-haiku-4-5",
                max_tokens=120,
                use_cache=False,
            )
            cleaned = self._sanitize_comment(comment)
            try:
                from core.cross_platform_brain import cross_platform_brain as _brain
                cleaned = _brain.sanitize_social_text(cleaned, max_chars=300)
            except Exception:
                pass
            return cleaned if self._is_confident_comment(cleaned) else ""
        except Exception as e:
            logger.warning(f"Reddit comment generation failed: {e}")
            # Fallback to template
            import random
            style = random.choice(_COMMENT_STYLES)
            niche = _COMMENT_SUBS.get(subreddit, "general")
            fallback = style.format(
                adjective=random.choice(["underrated", "interesting", "overlooked"]),
                extra=self._get_insight(niche, post_title),
                counter=self._get_counter(niche),
                observation=self._get_observation(niche),
                topic=post_title.split()[:3][0] if post_title else "this",
            )[:300]
            return fallback if self._is_confident_comment(fallback) else ""

    def run_auto_interaction(self, max_comments: int = 2) -> dict:
        """
        Generate and post comments on high-signal Reddit opportunities.
        Returns: {attempted, posted, skipped, errors}
        """
        if not settings.reddit_auto_enabled:
            return {"attempted": 0, "posted": 0, "skipped": 0, "errors": ["reddit_auto_disabled"]}

        if not self._reddit_ready() and not self._reddit_browser_ready():
            return {"attempted": 0, "posted": 0, "skipped": 0, "errors": ["reddit_credentials_missing"]}

        opportunities = sorted(
            self.get_posting_opportunities(),
            key=lambda o: int(o.get("score", 0)),
            reverse=True,
        )

        attempted = 0
        posted = 0
        skipped = 0
        errors: list[str] = []
        posted_items: list[dict] = []
        skipped_items: list[dict] = []

        for item in opportunities:
            if posted >= max_comments:
                break

            try:
                from core.cross_platform_brain import cross_platform_brain as _brain
                if _brain.is_topic_recent(item.get("title", ""), lookback=35):
                    skipped += 1
                    skipped_items.append({
                        "url": item.get("url", ""),
                        "title": item.get("title", "")[:120],
                        "reason": "recent_cross_platform_topic",
                    })
                    continue
            except Exception:
                pass

            post_id = self._post_id_from_url(item.get("url", ""))
            if not post_id:
                skipped += 1
                skipped_items.append({
                    "url": item.get("url", ""),
                    "reason": "invalid_post_url",
                })
                continue
            if memory.get(f"reddit_commented:{post_id}", ""):
                skipped += 1
                skipped_items.append({
                    "post_id": post_id,
                    "url": item.get("url", ""),
                    "reason": "already_commented",
                })
                continue

            comment_text = (item.get("comment") or "").strip()
            if not self._is_confident_comment(comment_text):
                skipped += 1
                skipped_items.append({
                    "post_id": post_id,
                    "url": item.get("url", ""),
                    "title": item.get("title", "")[:120],
                    "reason": "low_confidence_comment",
                })
                continue

            attempted += 1
            comment_id = self.post_comment(item.get("url", ""), comment_text)
            if comment_id:
                posted += 1
                posted_items.append({
                    "post_id": post_id,
                    "comment_id": comment_id,
                    "subreddit": item.get("subreddit", ""),
                    "title": item.get("title", "")[:120],
                    "url": item.get("url", ""),
                    "comment": comment_text,
                })
                try:
                    from core.cross_platform_brain import cross_platform_brain as _brain
                    _brain.record_topic("reddit", item.get("title", ""), source=item.get("subreddit", ""))
                except Exception:
                    pass
                memory.queue_notification(
                    f"🧠 Reddit: commented in r/{item.get('subreddit','?')} — {item.get('title','')[:80]}"
                )
                time.sleep(random.uniform(8, 20))
            else:
                errors.append(f"post_failed:{post_id}")

        return {
            "attempted": attempted,
            "posted": posted,
            "skipped": skipped,
            "errors": errors,
            "posted_items": posted_items,
            "skipped_items": skipped_items,
        }

    def get_posting_opportunities(self) -> list[dict]:
        """
        Return posts where Ken could add value with a comment.
        """
        ideas = reddit_miner.mine()
        return [
            {
                "subreddit": i["subreddit"],
                "title":     i["title"],
                "url":       i["url"],
                "score":     i["score"],
                "comment":   self.generate_comment(i["title"], i["subreddit"]),
            }
            for i in ideas[:8]
        ]

    def format_opportunities(self) -> str:
        opps = self.get_posting_opportunities()
        if not opps:
            return "no Reddit opportunities found right now"
        lines = ["*Reddit posting opportunities:*\n"]
        for o in opps[:5]:
            lines.append(f"r/{o['subreddit']}: *{o['title'][:70]}*")
            lines.append(f"  comment: {o['comment'][:100]}...")
            lines.append(f"  url: {o['url']}\n")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────

    def _get_insight(self, niche: str, title: str) -> str:
        insights = {
            "gaming_esports": "the meta shift is already happening — most people are behind.",
            "tech_ai":        "the real disruption isn't what everyone's focused on.",
            "cricket":        "India's approach here has been consistent for 2 seasons.",
            "bangalore_local": "lived there for years, this is extremely accurate.",
            "general":        "worth digging into the actual numbers on this.",
        }
        return insights.get(niche, insights["general"])

    def _get_counter(self, niche: str) -> str:
        counters = {
            "gaming_esports": "mechanical skill still matters more than people think",
            "tech_ai":        "the timeline everyone's predicting is probably off by 2-3 years",
            "cricket":        "the bowling attack is what actually decides series",
            "general":        "the obvious answer usually isn't the real answer here",
        }
        return counters.get(niche, counters["general"])

    def _get_observation(self, niche: str) -> str:
        observations = {
            "gaming_esports": "the community has shifted a lot in the last season",
            "tech_ai":        "most discourse around this misses the practical implementation side",
            "cricket":        "the domestic circuit is producing better talent than it gets credit for",
            "general":        "the pattern here repeats more than people notice",
        }
        return observations.get(niche, observations["general"])


reddit_engine = RedditEngine()
