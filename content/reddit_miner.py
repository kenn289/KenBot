"""
KenBot OS — Reddit Miner
Scans subreddits relevant to Kenneth's brand for viral ideas.
Extracts posts suitable for tweets, threads, and YouTube Shorts.
"""
from __future__ import annotations

import json
import time
from typing import Optional

import requests

from memory.store import memory
from utils.logger import logger

_CACHE_KEY = "reddit_mine_cache"
_CACHE_TTL  = 3600  # 1 hour

_SUBREDDITS = [
    "AskReddit",
    "funny",
    "gaming",
    "Cricket",
    "technology",
    "india",
    "valorant",
    "learnprogramming",
]

_HEADERS = {"User-Agent": "KenBot/1.0 (+personal project)"}
_MIN_SCORE = 500  # only posts with 500+ upvotes


class RedditMiner:

    def mine(self, subreddits: Optional[list[str]] = None, force: bool = False) -> list[dict]:
        """
        Returns list of viral ideas from Reddit:
        {title, score, url, subreddit, content_types, relevance}
        """
        cached = self._load_cache()
        if cached and not force:
            return cached

        subs = subreddits or _SUBREDDITS
        ideas: list[dict] = []

        for sub in subs:
            ideas.extend(self._fetch_sub(sub))

        # Sort by score
        ideas.sort(key=lambda x: x["score"], reverse=True)
        ideas = ideas[:30]

        self._save_cache(ideas)
        return ideas

    def tweet_ideas(self, limit: int = 5) -> list[str]:
        """Return top Reddit titles filtered for tweet potential."""
        ideas = self.mine()
        tweet_worthy = [
            i["title"] for i in ideas
            if "tweet" in i.get("content_types", [])
        ]
        return tweet_worthy[:limit]

    def video_ideas(self, limit: int = 3) -> list[str]:
        ideas = self.mine()
        return [
            i["title"] for i in ideas
            if "video" in i.get("content_types", [])
        ][:limit]

    def format_briefing(self, n: int = 5) -> str:
        ideas = self.mine()[:n]
        if not ideas:
            return "no Reddit ideas mined yet"
        lines = [f"*top Reddit ideas right now:*"]
        for i in ideas:
            lines.append(f"• [{i['subreddit']}] {i['title'][:80]} ({i['score']} pts)")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────

    def _fetch_sub(self, sub: str) -> list[dict]:
        try:
            url = f"https://www.reddit.com/r/{sub}/hot.json?limit=15"
            r = requests.get(url, headers=_HEADERS, timeout=8)
            if r.status_code != 200:
                return []
            posts = r.json().get("data", {}).get("children", [])
            results = []
            for post in posts:
                p = post.get("data", {})
                score = p.get("score", 0)
                if score < _MIN_SCORE:
                    continue
                title = p.get("title", "")
                results.append({
                    "title":         title,
                    "score":         score,
                    "url":           f"https://reddit.com{p.get('permalink', '')}",
                    "subreddit":     sub,
                    "content_types": self._classify(title, sub),
                    "relevance":     self._relevance(title),
                })
            return results
        except Exception as e:
            logger.debug(f"Reddit mine [{sub}] failed: {e}")
            return []

    def _classify(self, title: str, sub: str) -> list[str]:
        types = []
        t = title.lower()
        if len(t) < 140:
            types.append("tweet")
        if sub in ("AskReddit", "funny", "gaming", "Cricket"):
            types.append("thread")
        if "how" in t or "why" in t or "best" in t or "top" in t:
            types.append("video")
        return types or ["tweet"]

    def _relevance(self, title: str) -> int:
        keywords = ["valorant", "cricket", "ai", "bangalore", "india", "gaming",
                    "python", "startup", "kohli", "ranked"]
        t = title.lower()
        return sum(1 for k in keywords if k in t) * 20

    def _load_cache(self) -> Optional[list]:
        try:
            raw = memory.get(_CACHE_KEY, "")
            if not raw:
                return None
            data = json.loads(raw)
            if time.time() - data.get("ts", 0) > _CACHE_TTL:
                return None
            return data.get("ideas", [])
        except Exception:
            return None

    def _save_cache(self, ideas: list) -> None:
        memory.set(_CACHE_KEY, json.dumps({"ts": time.time(), "ideas": ideas}))


reddit_miner = RedditMiner()
