"""
Ken ClawdBot — Twitter/X Poster
Handles tweet posting, threading, and scheduled content.
Uses Tweepy v4 (Twitter API v2).

Free tier limits:
  - 1,500 tweets/month (post only)
  - No search read on free tier (use paid for replies)
  - We rate-limit conservatively: max 8 tweets/day
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Optional

import tweepy

from config.settings import settings
from core.ai_engine import ken_ai
from memory.store import memory
from utils.helpers import fingerprint, truncate, clean_for_tweet
from utils.logger import logger

# ── Daily tweet budget (conservative for free tier) ──────
MAX_TWEETS_PER_DAY = 8


class TwitterPoster:
    def __init__(self) -> None:
        self._client: Optional[tweepy.Client] = None
        self._api_v1: Optional[tweepy.API] = None
        self._ready = False
        self._init()

    def _init(self) -> None:
        if not all([
            settings.twitter_api_key,
            settings.twitter_api_secret,
            settings.twitter_access_token,
            settings.twitter_access_token_secret,
        ]):
            logger.warning("Twitter API keys not configured. Twitter features disabled.")
            return

        try:
            # v2 client (for posting tweets)
            self._client = tweepy.Client(
                consumer_key=settings.twitter_api_key,
                consumer_secret=settings.twitter_api_secret,
                access_token=settings.twitter_access_token,
                access_token_secret=settings.twitter_access_token_secret,
                wait_on_rate_limit=True,
            )
            # v1.1 api (for media upload — still needed for images)
            auth = tweepy.OAuth1UserHandler(
                settings.twitter_api_key,
                settings.twitter_api_secret,
                settings.twitter_access_token,
                settings.twitter_access_token_secret,
            )
            self._api_v1 = tweepy.API(auth, wait_on_rate_limit=True)
            self._ready = True
            logger.info("Twitter client initialized ✓")
        except Exception as exc:
            logger.error(f"Twitter init failed: {exc}")

    @property
    def ready(self) -> bool:
        return self._ready

    # ── Budget guard ──────────────────────────────────────
    def _tweets_today(self) -> int:
        key = f"tweets_today_{datetime.utcnow().date()}"
        return int(memory.get(key, "0"))

    def _increment_tweet_count(self) -> None:
        key = f"tweets_today_{datetime.utcnow().date()}"
        count = self._tweets_today() + 1
        memory.set(key, str(count))

    def _can_tweet(self) -> bool:
        count = self._tweets_today()
        if count >= MAX_TWEETS_PER_DAY:
            logger.warning(f"Daily tweet budget hit ({MAX_TWEETS_PER_DAY}). Skipping.")
            return False
        return True

    # ── Core post ─────────────────────────────────────────
    def post_tweet(self, text: str, reply_to_id: Optional[str] = None) -> Optional[str]:
        """
        Post a single tweet. Returns tweet ID or None on failure.
        Skips if content was already posted (dedup).
        """
        if not self._ready:
            logger.warning("Twitter not ready, tweet skipped.")
            return None

        if not self._can_tweet():
            return None

        text = clean_for_tweet(text)
        text = truncate(text, 280)
        h = fingerprint(text)

        if memory.already_posted(h):
            logger.info(f"Tweet already posted (dedup), skipping: {text[:50]}")
            return None

        try:
            kwargs: dict = {"text": text}
            if reply_to_id:
                kwargs["in_reply_to_tweet_id"] = reply_to_id

            response = self._client.create_tweet(**kwargs)  # type: ignore
            tweet_id = str(response.data["id"])
            memory.mark_posted(h, "twitter", text, tweet_id)
            self._increment_tweet_count()
            logger.info(f"✅ Tweet posted [{tweet_id}]: {text[:60]}…")
            return tweet_id
        except tweepy.TooManyRequests:
            logger.warning("Twitter rate limit hit, waiting 15 min…")
            time.sleep(900)
            return None
        except Exception as exc:
            logger.error(f"Tweet failed: {exc}")
            return None

    def post_thread(self, tweets: list[str]) -> list[str]:
        """
        Post a tweet thread. Each tweet replies to the previous one.
        Returns list of posted tweet IDs.
        """
        if not tweets:
            return []

        ids: list[str] = []
        prev_id: Optional[str] = None

        for i, tweet in enumerate(tweets):
            numbered = f"{i+1}/{len(tweets)} {tweet}" if len(tweets) > 1 else tweet
            tweet_id = self.post_tweet(numbered, reply_to_id=prev_id)
            if tweet_id:
                ids.append(tweet_id)
                prev_id = tweet_id
                time.sleep(3)  # Small gap between thread tweets
            else:
                logger.warning(f"Thread tweet {i+1} failed, stopping thread")
                break

        return ids

    # ── High-level content actions ────────────────────────
    def post_content_tweet(self, topic: Optional[str] = None) -> Optional[str]:
        """
        Generate and post a tweet on a topic.
        If no topic provided, Ken picks one from content pillars.
        """
        if not topic:
            picked = ken_ai.pick_content_topic()
            topic = f"{picked.get('topic')}: {picked.get('angle')}"

        logger.info(f"Generating tweet on: {topic}")
        tweet_text = ken_ai.generate_tweet(topic, style="hot take")
        return self.post_tweet(tweet_text)

    def post_content_thread(self, topic: Optional[str] = None, num_tweets: int = 5) -> list[str]:
        """Generate and post a tweet thread."""
        if not topic:
            picked = ken_ai.pick_content_topic()
            topic = f"{picked.get('topic')}: {picked.get('angle')}"

        logger.info(f"Generating thread on: {topic}")
        tweets = ken_ai.generate_tweet_thread(topic, num_tweets=num_tweets)
        return self.post_thread(tweets)


# Singleton
twitter = TwitterPoster()
