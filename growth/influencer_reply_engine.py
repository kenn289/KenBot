"""
KenBot OS — Influencer Reply Engine
Scans Twitter for viral/trending tweets from influencers
in Ken's niches and generates clever first-mover replies.
Goal: visibility through witty replies on viral content.
"""
from __future__ import annotations

import json
import time
from typing import Optional

from memory.store import memory
from utils.logger import logger

_CACHE_KEY = "influencer_reply_cache"
_CACHE_TTL  = 1800  # 30 min

# Target accounts by niche — replies on their viral tweets gain visibility
_TARGET_ACCOUNTS: dict[str, list[str]] = {
    "gaming_esports": ["tenz", "shroud", "tarik", "NRG", "sentinels", "valorant"],
    "cricket":        ["imVkohli", "msdhoni", "BCCI", "IPL", "CricketTwitter"],
    "tech_ai":        ["sama", "karpathy", "anthropic", "openai", "ylecun"],
    "india_startup":  ["kumarr", "zerodha", "nikhilkamath"],
    "bangalore":      ["bang알_", "peakbengaluru"],
}

# Reply style hooks that get engagement
_REPLY_HOOKS = [
    "ngl this aged {direction}",
    "took {entity} long enough to realise this",
    "counterpoint: {counterpoint}",
    "as someone who {context}, this is extremely accurate",
    "nobody talking about the fact that {observation}",
    "the {topic} discourse needed this",
    "wait until they find out about {thing}",
    "the timeline really said {reaction} today",
]


class InfluencerReplyEngine:
    """
    Generates reply hooks to viral tweets.
    Actual posting handled by twitter/poster.py.
    Twitter API scraping requires bearer token.
    """

    def get_reply_hook(
        self,
        original_tweet: str,
        account_niche: str = "tech_ai",
        *,
        topic: Optional[str] = None,
    ) -> str:
        """
        Generate a clever reply to a viral tweet.
        Returns a tweet string <= 240 chars.
        """
        import random
        hook = random.choice(_REPLY_HOOKS)
        direction = random.choice(["well", "badly", "like prophecy"])
        entity = random.choice(["everyone", "them", "the internet"])
        topic_str = topic or self._extract_topic(original_tweet)

        reply = hook.format(
            direction=direction,
            entity=entity,
            counterpoint=f"the real issue is {topic_str}",
            context="watching this space",
            observation=f"{topic_str} was always going to end this way",
            topic=topic_str,
            thing=f"what actually happened with {topic_str}",
            reaction="chaos",
        )
        return reply[:240]

    def generate_reply_to(self, tweet_text: str, author: str = "") -> str:
        """
        Generate a genuine Ken-voice reply to a viral tweet using Claude + live context.
        """
        try:
            from core.ai_engine import ken_ai
            from core.news_fetcher import news_fetcher as _nf
            from config.ken_personality import IDENTITY

            # Get live context on the topic so the reply is grounded in facts
            topic = self._extract_topic(tweet_text)
            live_ctx = ""
            try:
                live_ctx = _nf.get_news_context_for_claude(tweet_text[:120])
            except Exception:
                pass

            ctx_block = ""
            if live_ctx:
                ctx_block = (
                    f"\n\nLIVE CONTEXT on this topic:\n{live_ctx}\n"
                    "Use this to make your reply factually current."
                )

            system = (
                f"{IDENTITY}\n\n"
                "You are replying to a viral tweet on X (Twitter). "
                "Write ONE reply in Kenneth's voice — max 240 chars, lowercase, casual. "
                "No hashtags. No clout-chasing opener. Sound like a real person, not a brand. "
                "Be punchy — a hot take, a counter, or a genuinely interesting observation. "
                "Do NOT start with the person's @handle. Just say the thing."
                + ctx_block
            )
            at = f"@{author} " if author else ""
            prompt = f"Original tweet: {at}{tweet_text}\n\nWrite your reply:"
            reply = ken_ai._call(system, prompt, model="claude-haiku-4-5", max_tokens=80, use_cache=False)
            # Prepend @handle for context but keep it short
            if author and not reply.lower().startswith(f"@{author.lower()}"):
                reply = f"@{author} {reply}"
            return reply[:240]
        except Exception as e:
            logger.warning(f"generate_reply_to failed: {e}")
            return ""

    def fetch_viral_tweets(self) -> list[dict]:
        """
        Fetch recent viral tweets from target accounts.
        Requires Twitter API v2 bearer token.
        Falls back to empty list if not configured.
        """
        from config.settings import settings
        if not settings.twitter_bearer_token:
            logger.debug("Twitter bearer not set — skipping influencer scan")
            return []

        cached = self._load_cache()
        if cached:
            return cached

        targets = [t for niche in _TARGET_ACCOUNTS.values() for t in niche][:5]
        tweets = []

        try:
            import requests
            headers = {"Authorization": f"Bearer {settings.twitter_bearer_token}"}
            for handle in targets[:3]:  # limit API calls
                url = f"https://api.twitter.com/2/tweets/search/recent"
                params = {
                    "query": f"from:{handle} -is:retweet",
                    "max_results": 5,
                    "tweet.fields": "public_metrics",
                }
                r = requests.get(url, headers=headers, params=params, timeout=10)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    for t in data:
                        metrics = t.get("public_metrics", {})
                        if metrics.get("like_count", 0) > 500:
                            tweets.append({
                                "id":     t["id"],
                                "text":   t["text"],
                                "author": handle,
                                "likes":  metrics.get("like_count", 0),
                            })
        except Exception as e:
            logger.debug(f"Influencer fetch failed: {e}")

        tweets.sort(key=lambda x: x.get("likes", 0), reverse=True)
        self._save_cache(tweets)
        return tweets

    # ── Internal ──────────────────────────────────────────────────────────

    def _extract_topic(self, text: str) -> str:
        keywords = {
            "valorant": "Valorant", "cricket": "cricket", "ai": "AI",
            "ipl": "IPL", "kohli": "Virat", "bangalore": "Bangalore",
            "tenz": "TenZ", "ranked": "ranked",
        }
        t = text.lower()
        for kw, label in keywords.items():
            if kw in t:
                return label
        return "this"

    def _load_cache(self) -> Optional[list]:
        try:
            raw = memory.get(_CACHE_KEY, "")
            if not raw:
                return None
            data = json.loads(raw)
            if time.time() - data.get("ts", 0) > _CACHE_TTL:
                return None
            return data.get("tweets", [])
        except Exception:
            return None

    def _save_cache(self, tweets: list) -> None:
        memory.set(_CACHE_KEY, json.dumps({"ts": time.time(), "tweets": tweets}))


influencer_reply_engine = InfluencerReplyEngine()
