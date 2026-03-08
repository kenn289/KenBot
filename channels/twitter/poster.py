"""
Ken ClawdBot -- Twitter/X Poster
Primary: Twitter API v2 via tweepy (instant, no bot-detection).
Fallback: Playwright browser automation (used if API keys are missing).
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
        self._api_ready = bool(
            settings.twitter_api_key
            and settings.twitter_api_secret
            and settings.twitter_access_token
            and settings.twitter_access_token_secret
        )
        self._browser_ready = bool(settings.twitter_username and settings.twitter_password)

        if self._api_ready:
            logger.info("Twitter: API v2 mode (tweepy)")
        elif self._browser_ready:
            logger.info("Twitter: browser automation mode (Playwright)")
        else:
            logger.warning("Twitter not configured — set API keys or TWITTER_USERNAME/PASSWORD")

    @property
    def ready(self) -> bool:
        return self._api_ready or self._browser_ready

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

    # ── Primary: Twitter API v2 ───────────────────────────────────────────────

    def _post_via_api(self, text: str) -> Optional[str]:
        """Post via Twitter API v2 using tweepy. Returns tweet ID or None."""
        try:
            import tweepy
        except ImportError:
            logger.error("tweepy not installed: pip install tweepy")
            return None
        try:
            client = tweepy.Client(
                bearer_token=settings.twitter_bearer_token or None,
                consumer_key=settings.twitter_api_key,
                consumer_secret=settings.twitter_api_secret,
                access_token=settings.twitter_access_token,
                access_token_secret=settings.twitter_access_token_secret,
                wait_on_rate_limit=True,
            )
            response = client.create_tweet(text=text)
            tweet_id = str(response.data["id"])
            logger.info(f"Tweet posted via API: {tweet_id} — {text[:60]}...")
            return tweet_id
        except tweepy.Unauthorized:
            logger.error(
                "Twitter API 401 Unauthorized — API keys are invalid or app lacks Write permission. "
                "Fix: developer.twitter.com → your app → Settings → set permissions to "
                "'Read and Write', then regenerate Access Token & Secret and update .env"
            )
            return None
        except tweepy.Forbidden as e:
            logger.error(f"Twitter API 403 Forbidden — {e}. Free tier may not support tweet creation.")
            return None
        except Exception as e:
            logger.error(f"API tweet failed: {e}")
            return None

    # ── Fallback: Playwright browser automation ───────────────────────────────

    def _post_via_browser(self, text: str) -> Optional[str]:
        """Post via headless Playwright. Returns 'browser_post_ok' or None."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            logger.error("Playwright not installed. Run: .venv/Scripts/python -m playwright install chromium")
            return None

        debug_dir = Path(settings.root_dir) / "logs"
        debug_dir.mkdir(parents=True, exist_ok=True)

        with sync_playwright() as pw:
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
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
                Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
                window.chrome = { runtime: {} };
            """)

            if SESSION_PATH.exists():
                try:
                    cookies = json.loads(SESSION_PATH.read_text())
                    if cookies:
                        context.add_cookies(cookies)
                except Exception:
                    SESSION_PATH.unlink(missing_ok=True)

            page = context.new_page()

            def _ensure_logged_in() -> bool:
                page.goto("https://x.com/home", wait_until="domcontentloaded", timeout=30000)
                try:
                    page.locator('[data-testid="SideNav_NewTweet_Button"]').first.wait_for(
                        state="visible", timeout=7000
                    )
                    return True
                except Exception:
                    pass
                SESSION_PATH.unlink(missing_ok=True)
                if not self._login(page):
                    return False
                SESSION_PATH.write_text(json.dumps(context.cookies()))
                return True

            def _find_compose() -> Optional[object]:
                page.goto("https://x.com/compose/tweet", wait_until="domcontentloaded", timeout=30000)
                time.sleep(random.uniform(1.5, 2.5))
                if "compose" not in page.url:
                    logger.warning(f"compose/tweet redirected to: {page.url}")
                    return None
                for sel in [
                    '[data-testid="tweetTextarea_0"]',
                    '[role="dialog"] [role="textbox"]',
                    '[role="textbox"]',
                ]:
                    el = page.locator(sel).first
                    try:
                        el.wait_for(state="visible", timeout=8000)
                        logger.info(f"Compose textarea: {sel}")
                        return el
                    except Exception:
                        continue
                return None

            try:
                if not _ensure_logged_in():
                    browser.close()
                    return None

                compose = _find_compose()
                if compose is None:
                    page.screenshot(path=str(debug_dir / "tweet_compose_fail.png"))
                    logger.error("Compose box not found — screenshot: logs/tweet_compose_fail.png")
                    browser.close()
                    return None

                compose.click()
                time.sleep(0.4)
                compose.fill(text)
                time.sleep(random.uniform(0.8, 1.5))

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
                    page.screenshot(path=str(debug_dir / "tweet_button_fail.png"))
                    logger.error("Post button not found — screenshot: logs/tweet_button_fail.png")
                    browser.close()
                    return None

                post_btn.click()
                time.sleep(random.uniform(2, 3))
                SESSION_PATH.write_text(json.dumps(context.cookies()))
                browser.close()
                return "browser_post_ok"

            except Exception as e:
                logger.error(f"Browser tweet failed: {e}")
                try:
                    page.screenshot(path=str(debug_dir / "tweet_error.png"))
                except Exception:
                    pass
                browser.close()
                return None

    def _login(self, page) -> bool:
        """Log in to X via the browser login flow."""
        try:
            from playwright.sync_api import TimeoutError as PWTimeout
            page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded", timeout=30000)
            time.sleep(2)

            # Step 1: Username
            page.locator('input[autocomplete="username"]').first.wait_for(state="visible", timeout=15000)
            page.locator('input[autocomplete="username"]').first.fill(settings.twitter_username)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(2)

            # Step 2: Optional phone/email/phone verification step
            try:
                verify = page.locator('input[data-testid="ocfEnterTextTextInput"]').first
                verify.wait_for(state="visible", timeout=5000)
                # Use email first, then phone, then username as last resort
                verify_value = settings.twitter_email or settings.twitter_phone or settings.twitter_username
                if not (settings.twitter_email or settings.twitter_phone):
                    logger.warning(
                        "X verification step appeared but TWITTER_EMAIL and TWITTER_PHONE are not set "
                        "in .env \u2014 add one of them so bot can pass the verification step"
                    )
                verify.fill(verify_value)
                page.keyboard.press("Enter")
                time.sleep(2)
            except PWTimeout:
                pass  # No verification step — proceed directly to password

            # Step 3: Password
            page.locator('input[name="password"]').first.wait_for(state="visible", timeout=15000)
            page.locator('input[name="password"]').first.fill(settings.twitter_password)
            time.sleep(0.5)
            page.keyboard.press("Enter")
            time.sleep(4)

            if "home" in page.url:
                logger.info("Twitter browser login successful")
                return True
            logger.error(f"Browser login failed — URL after login: {page.url}")
            return False
        except Exception as e:
            logger.error(f"Browser login failed: {e}")
            return False

    # ── Public interface ──────────────────────────────────────────────────────

    def post_tweet(self, text: str) -> Optional[str]:
        """Post a tweet. Tries API v2 first, then Playwright browser fallback."""
        if not self.ready:
            logger.warning("Twitter not configured.")
            return None
        if not self._can_tweet():
            return None

        text = clean_for_tweet(truncate(text, 280))
        h = fingerprint(text)
        if memory.already_posted(h):
            logger.info(f"Tweet already posted (dedup): {text[:50]}")
            return None

        result = None

        if self._api_ready:
            result = self._post_via_api(text)

        if not result and self._browser_ready:
            logger.info("API post failed or unavailable — falling back to browser")
            result = self._post_via_browser(text)

        if result:
            memory.mark_posted(h, "twitter", text, "api" if self._api_ready else "browser")
            self._increment()
            memory.queue_notification(f"\U0001f426 tweeted: {text[:120]}")
        else:
            logger.error("Tweet failed via all methods")

        return result

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
