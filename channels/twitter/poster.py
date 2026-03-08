"""
Ken ClawdBot -- Twitter/X Poster
Posts tweets via Playwright browser automation (no paid API needed).
Session cookies saved to credentials/twitter_session.json after first login.
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from config.settings import settings
from core.ai_engine import ken_ai
from memory.store import memory
from utils.helpers import fingerprint, truncate, clean_for_tweet
from utils.logger import logger

SESSION_PATH = Path(settings.root_dir) / "credentials" / "twitter_session.json"
MAX_TWEETS_PER_DAY = 8


class TwitterPoster:
    def __init__(self) -> None:
        self._ready = bool(settings.twitter_username and settings.twitter_password)
        if not self._ready:
            logger.warning("TWITTER_USERNAME / TWITTER_PASSWORD not set -- Twitter disabled.")

    @property
    def ready(self) -> bool:
        return self._ready

    def _tweets_today(self) -> int:
        key = f"tweets_today_{datetime.utcnow().date()}"
        return int(memory.get(key, "0"))

    def _can_tweet(self) -> bool:
        if self._tweets_today() >= MAX_TWEETS_PER_DAY:
            logger.warning(f"Daily tweet budget hit ({MAX_TWEETS_PER_DAY}). Skipping.")
            return False
        return True

    def _increment(self) -> None:
        key = f"tweets_today_{datetime.utcnow().date()}"
        memory.set(key, str(self._tweets_today() + 1))

    def post_tweet(self, text: str) -> Optional[str]:
        """Post a tweet via browser automation. Returns 'browser_post_ok' or None."""
        if not self._ready:
            logger.warning("Twitter not configured.")
            return None
        if not self._can_tweet():
            return None

        text = clean_for_tweet(truncate(text, 280))
        h = fingerprint(text)
        if memory.already_posted(h):
            logger.info(f"Tweet already posted (dedup): {text[:50]}")
            return None

        try:
            from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout
        except ImportError:
            logger.error("Playwright not installed. Run: .venv/Scripts/python -m playwright install chromium")
            return None

        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                viewport={"width": 1280, "height": 900},
            )
            if SESSION_PATH.exists():
                try:
                    context.add_cookies(json.loads(SESSION_PATH.read_text()))
                    logger.info("Loaded Twitter session cookies")
                except Exception:
                    pass

            page = context.new_page()
            try:
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
                time.sleep(2)

                # Reliable login check: look for the compose sidebar button
                is_logged_in = (
                    "login" not in page.url
                    and page.url.rstrip("/") != "https://x.com"
                    and page.locator('[data-testid="SideNav_NewTweet_Button"]').count() > 0
                )
                if not is_logged_in:
                    logger.info("Not logged in -- starting login flow")
                    if not self._login(page):
                        browser.close()
                        return None
                    SESSION_PATH.write_text(json.dumps(context.cookies()))
                    logger.info("Session cookies saved")

                # Navigate directly to the compose modal (most reliable path)
                page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(1.5, 2.5))

                # Try primary selector, then fallback to generic textbox
                compose = None
                for selector in [
                    '[data-testid="tweetTextarea_0"]',
                    '[data-testid="tweetTextarea_0_label"] + div [role="textbox"]',
                    '[role="dialog"] [role="textbox"]',
                    '[role="textbox"]',
                ]:
                    el = page.locator(selector).first
                    try:
                        el.wait_for(state="visible", timeout=8000)
                        compose = el
                        logger.info(f"Compose box found via selector: {selector}")
                        break
                    except Exception:
                        continue

                if compose is None:
                    raise RuntimeError("Could not find compose textarea with any selector")

                compose.click()
                time.sleep(0.5)

                for char in text:
                    compose.type(char, delay=random.randint(20, 60))

                time.sleep(random.uniform(0.8, 1.5))

                # Submit button — try inline first, then modal variant
                post_btn = None
                for btn_sel in ['[data-testid="tweetButton"]', '[data-testid="tweetButtonInline"]']:
                    el = page.locator(btn_sel).first
                    try:
                        el.wait_for(state="visible", timeout=8000)
                        post_btn = el
                        break
                    except Exception:
                        continue

                if post_btn is None:
                    raise RuntimeError("Could not find post button")

                post_btn.click()
                time.sleep(random.uniform(2, 3))

                SESSION_PATH.write_text(json.dumps(context.cookies()))
                memory.mark_posted(h, "twitter", text, "browser")
                self._increment()
                logger.info(f"Tweet posted: {text[:60]}...")
                memory.queue_notification(f"\ud83d\udc26 tweeted: {text[:120]}")
                browser.close()
                return "browser_post_ok"

            except Exception as e:
                logger.error(f"Tweet failed: {e}")
                browser.close()
                return None

    def _login(self, page) -> bool:
        try:
            from playwright.sync_api import TimeoutError as PWTimeout
            page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            page.locator('input[autocomplete="username"]').first.wait_for(state="visible", timeout=15000)
            page.locator('input[autocomplete="username"]').first.fill(settings.twitter_username)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(2)

            try:
                verify = page.locator('input[data-testid="ocfEnterTextTextInput"]').first
                verify.wait_for(state="visible", timeout=5000)
                verify.fill(settings.twitter_email or settings.twitter_username)
                page.keyboard.press("Enter")
                time.sleep(2)
            except PWTimeout:
                pass

            page.locator('input[name="password"]').first.wait_for(state="visible", timeout=15000)
            page.locator('input[name="password"]').first.fill(settings.twitter_password)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(4)

            if "home" in page.url:
                logger.info("Twitter login successful")
                return True
            logger.error(f"Login may have failed -- URL: {page.url}")
            return False
        except Exception as e:
            logger.error(f"Login failed: {e}")
            return False

    def post_thread(self, tweets: list[str]) -> list[str]:
        ids = []
        for i, tweet in enumerate(tweets):
            result = self.post_tweet(tweet)
            if result:
                ids.append(result)
                if i < len(tweets) - 1:
                    time.sleep(random.uniform(8, 15))
            else:
                break
        return ids

    def post_content_tweet(self, topic: Optional[str] = None) -> Optional[str]:
        if not topic:
            picked = ken_ai.pick_content_topic()
            topic = f"{picked.get('topic')}: {picked.get('angle')}"
        logger.info(f"Generating tweet on: {topic}")
        return self.post_tweet(ken_ai.generate_tweet(topic, style="hot take"))

    def post_content_thread(self, topic: Optional[str] = None, num_tweets: int = 5) -> list[str]:
        if not topic:
            picked = ken_ai.pick_content_topic()
            topic = f"{picked.get('topic')}: {picked.get('angle')}"
        logger.info(f"Generating thread on: {topic}")
        return self.post_thread(ken_ai.generate_tweet_thread(topic, num_tweets=num_tweets))


# Singleton
twitter = TwitterPoster()
