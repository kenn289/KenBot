"""
KenBot OS — Trend Scanner
Aggregates trending topics from multiple sources and scores them
for relevance to Kenneth's brand (gaming, cricket, tech, Bangalore).
"""
from __future__ import annotations

import json
import random
import time
from datetime import datetime
from typing import Optional

import requests

from memory.store import memory
from config.settings import settings
from utils.logger import logger

_CACHE_KEY = "trend_cache"
_CACHE_TTL = 1800  # 30 minutes


# Subreddits that map to Ken's interests
_REDDIT_SUBS = [
    "r/gaming",
    "r/valorant",
    "r/Cricket",
    "r/india",
    "r/technology",
    "r/artificial",
    "r/bangalore",
    "r/learnprogramming",
    "r/ProgrammerHumor",
    "r/MachineLearning",
    "r/ChatGPT",
    "r/webdev",
    "r/formula1",
    "r/nba",
    "r/movies",
    "r/TrueOffMyChest",
    "r/memes",
    "r/funny",
    "r/AskIndia",
    "r/IndianGaming",
]

# Keywords that boost relevance score for Ken's account
_KEN_KEYWORDS = [
    # Valorant pros — full scene
    "valorant", "vct", "tenz", "sentinels", "zekken", "sacy", "pancada",
    "fns", "boaster", "tarik", "shanks", "yay", "nats", "aspas", "derke",
    "demon1", "chronicle", "cned", "loud", "fnatic", "nrg", "100 thieves",
    "team liquid", "paper rex", "prx", "karmine", "eg", "navi",
    "vct americas", "vct emea", "vct pacific", "champions", "masters",
    "fps", "duelist", "igl", "esports", "streamer", "gaming",
    # Cricket
    "kohli", "rohit", "ipl", "bcci", "cricket", "t20", "rcb",
    # F1
    "f1", "formula 1", "verstappen", "max", "carlos sainz", "ferrari", "red bull",
    # Location
    "bangalore", "blr", "india",
    # Tech / AI
    "ai", "claude", "openai", "llm", "machine learning", "chatgpt", "gemini",
    "vibe coding", "cursor", "github copilot", "python", "developer", "startup",
    "tech layoffs", "software engineer", "leetcode",
    # Internet culture
    "meme", "viral", "trending", "twitter drama",
    # Pop culture
    "netflix", "marvel", "dc", "bollywood",
]


class TrendScanner:
    """
    Fetches and scores trends. Results cached for 30 minutes.
    All IO handled with graceful fallbacks — never crashes the main process.
    """

    def get_trends(self, force_refresh: bool = False) -> list[dict]:
        """
        Return a list of trend dicts:
        {topic, keywords, trend_velocity, virality_score, sentiment, relevance_score, source}
        """
        cached = self._load_cache()
        if cached and not force_refresh:
            return cached

        trends: list[dict] = []
        trends.extend(self._fetch_reddit_trends())
        trends.extend(self._generate_contextual_trends())

        # Score each trend for Ken's brand relevance
        for t in trends:
            t["relevance_score"] = self._score_relevance(t)

        # Sort by relevance then virality
        trends.sort(key=lambda x: (x["relevance_score"], x["virality_score"]), reverse=True)
        trends = trends[:20]

        self._save_cache(trends)
        return trends

    def top_topics(self, n: int = 5) -> list[str]:
        """Return the n most relevant topic strings."""
        return [t["topic"] for t in self.get_trends()[:n]]

    def most_relevant(self) -> Optional[dict]:
        trends = self.get_trends()
        return trends[0] if trends else None

    def cricket_update(self) -> str:
        """Return a live cricket news summary from ESPNcricinfo/Sportstar RSS."""
        from core.news_fetcher import news_fetcher
        return news_fetcher.get_cricket_update()

    # ── Internal ──────────────────────────────────────────────────────────

    def _fetch_reddit_trends(self) -> list[dict]:
        """Scrape r/all hot posts without auth (public JSON endpoint)."""
        trends = []
        try:
            headers = {"User-Agent": "KenBot/1.0 (personal project)"}
            r = requests.get(
                "https://www.reddit.com/r/all/hot.json?limit=25",
                headers=headers,
                timeout=8,
            )
            if r.status_code == 200:
                posts = r.json().get("data", {}).get("children", [])
                for post in posts[:15]:
                    p = post.get("data", {})
                    title = p.get("title", "")
                    score = p.get("score", 0)
                    sub = p.get("subreddit", "")
                    trends.append({
                        "topic":           title[:120],
                        "keywords":        title.lower().split()[:6],
                        "trend_velocity":  min(10, score // 5000),
                        "virality_score":  min(100, score // 1000),
                        "sentiment":       "neutral",
                        "relevance_score": 0,
                        "source":          f"reddit/{sub}",
                    })
        except Exception as e:
            logger.debug(f"Reddit trend fetch failed: {e}")
        return trends

    def _generate_contextual_trends(self) -> list[dict]:
        """Generate contextually relevant seeds based on Ken's interests."""
        now = datetime.utcnow()
        seeds = [
            {"topic": "TenZ Sentinels Valorant highlights", "keywords": ["tenz", "sentinels", "valorant"],
             "virality_score": 70, "trend_velocity": 6, "sentiment": "positive", "source": "contextual"},
            {"topic": "fns IGL callouts strategy Valorant", "keywords": ["fns", "igl", "valorant", "nrg"],
             "virality_score": 65, "trend_velocity": 5, "sentiment": "positive", "source": "contextual"},
            {"topic": "boaster Karmine Corp VCT", "keywords": ["boaster", "karmine", "vct"],
             "virality_score": 68, "trend_velocity": 6, "sentiment": "positive", "source": "contextual"},
            {"topic": "tarik streaming reacts Valorant", "keywords": ["tarik", "stream", "valorant"],
             "virality_score": 72, "trend_velocity": 6, "sentiment": "positive", "source": "contextual"},
            {"topic": "aspas LOUD clutch VCT Americas", "keywords": ["aspas", "loud", "vct"],
             "virality_score": 74, "trend_velocity": 7, "sentiment": "positive", "source": "contextual"},
            {"topic": "Derke Fnatic fragmovie VCT EMEA", "keywords": ["derke", "fnatic", "vct"],
             "virality_score": 69, "trend_velocity": 6, "sentiment": "positive", "source": "contextual"},
            {"topic": "VCT Americas standings results", "keywords": ["vct", "americas", "valorant"],
             "virality_score": 66, "trend_velocity": 6, "sentiment": "excited", "source": "contextual"},
            {"topic": "Valorant ranked patch meta update", "keywords": ["valorant", "ranked", "patch", "meta"],
             "virality_score": 60, "trend_velocity": 5, "sentiment": "mixed", "source": "contextual"},
            {"topic": "IPL 2026 drama", "keywords": ["ipl", "auction", "cricket", "rcb"],
             "virality_score": 75, "trend_velocity": 7, "sentiment": "excited", "source": "contextual"},
            {"topic": "AI replacing developers debate", "keywords": ["ai", "programming", "jobs"],
             "virality_score": 80, "trend_velocity": 8, "sentiment": "controversial", "source": "contextual"},
            {"topic": "Max Verstappen F1 season", "keywords": ["f1", "verstappen", "formula1"],
             "virality_score": 72, "trend_velocity": 6, "sentiment": "positive", "source": "contextual"},
            {"topic": "ChatGPT vs Claude debate", "keywords": ["chatgpt", "claude", "llm", "ai"],
             "virality_score": 78, "trend_velocity": 7, "sentiment": "controversial", "source": "contextual"},
            {"topic": "Vibe coding cursor AI developer", "keywords": ["vibe coding", "cursor", "ai", "developer"],
             "virality_score": 68, "trend_velocity": 6, "sentiment": "positive", "source": "contextual"},
            {"topic": "Software engineer memes leetcode", "keywords": ["developer", "programmer", "meme", "leetcode"],
             "virality_score": 74, "trend_velocity": 6, "sentiment": "funny", "source": "contextual"},
            {"topic": "Viral meme format this week", "keywords": ["meme", "viral", "twitter"],
             "virality_score": 85, "trend_velocity": 9, "sentiment": "funny", "source": "contextual"},
            {"topic": "Netflix new show review", "keywords": ["netflix", "webseries", "review"],
             "virality_score": 65, "trend_velocity": 5, "sentiment": "mixed", "source": "contextual"},
        ]
        # Add random relevance
        for s in seeds:
            s["relevance_score"] = 0
        return seeds

    def _score_relevance(self, trend: dict) -> int:
        """Score 0-100 how relevant this trend is to Ken's brand."""
        score = 0
        text = " ".join([trend.get("topic", "")] + trend.get("keywords", [])).lower()
        for kw in _KEN_KEYWORDS:
            if kw in text:
                score += 10
        score = min(100, score)
        # Boost by virality
        score = min(100, score + trend.get("virality_score", 0) // 5)
        return score

    def _load_cache(self) -> Optional[list]:
        try:
            raw = memory.get(_CACHE_KEY, "")
            if not raw:
                return None
            data = json.loads(raw)
            # Check TTL
            if time.time() - data.get("ts", 0) > _CACHE_TTL:
                return None
            return data.get("trends", [])
        except Exception:
            return None

    def _save_cache(self, trends: list) -> None:
        memory.set(_CACHE_KEY, json.dumps({"ts": time.time(), "trends": trends}))


trend_scanner = TrendScanner()
