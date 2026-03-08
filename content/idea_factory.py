"""
KenBot OS — Idea Factory
Generates daily content ideas: tweets, threads, video scripts.
Combines trend scanner + humor engine + content brain.
"""
from __future__ import annotations

import json
import random
from datetime import datetime
from typing import Optional

from content.trend_scanner import trend_scanner
from core.content_brain import content_brain
from core.humor_engine import humor_engine
from memory.store import memory
from utils.logger import logger

_KV_KEY = "idea_factory_today"


class IdeaFactory:
    """
    Generates a daily content plan:
    - 5+ tweet ideas
    - 2 thread ideas
    - 2 video ideas
    Cached per calendar day. Cleared on first call of a new day.
    """

    def get_daily_ideas(self, force_refresh: bool = False) -> dict:
        today = datetime.utcnow().strftime("%Y-%m-%d")
        cached = self._load_cached(today)
        if cached and not force_refresh:
            return cached

        trends = trend_scanner.top_topics(n=6)
        best_humor = humor_engine.best_category()

        tweet_ideas = self._generate_tweet_ideas(trends, best_humor)
        thread_ideas = content_brain.thread_ideas()
        video_ideas = self._generate_video_ideas(trends)

        ideas = {
            "date":         today,
            "tweet_ideas":  tweet_ideas,
            "thread_ideas": thread_ideas,
            "video_ideas":  video_ideas,
            "generated_at": datetime.utcnow().isoformat(),
        }
        self._save_cached(today, ideas)
        return ideas

    def format_briefing(self) -> str:
        """Format ideas as WhatsApp message for Kenneth."""
        ideas = self.get_daily_ideas()
        lines = [
            f"*KenBot daily ideas — {ideas['date']}*\n",
            "*tweet ideas (5):*",
        ]
        for i, t in enumerate(ideas["tweet_ideas"][:5], 1):
            lines.append(f"{i}. {t}")
        lines.append("\n*thread ideas (2):*")
        for t in ideas["thread_ideas"][:2]:
            lines.append(f"• {t}")
        lines.append("\n*video ideas (2):*")
        for v in ideas["video_ideas"][:2]:
            lines.append(f"• {v}")
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────

    def _generate_tweet_ideas(self, trends: list[str], best_humor: str) -> list[str]:
        ideas = []
        for topic in trends[:3]:
            hot_take = content_brain.hot_take(topic)
            ideas.append(hot_take["seed"])
        # Add humor-category specific ideas
        ideas.append(f"running out of [{best_humor.replace('_',' ')}] content — need to reload")
        ideas.append(content_brain.debate_starter())
        # Fill remaining with relatable
        while len(ideas) < 5:
            hot = content_brain.hot_take()
            ideas.append(hot["seed"])
        random.shuffle(ideas)
        return ideas[:7]

    def _generate_video_ideas(self, trends: list[str]) -> list[str]:
        gaming_ideas = [
            "TenZ's most insane play this week — ranked or scripted?",
            f"worst teammate types in Valorant ranked — a breakdown",
            "the most chaotic round I've ever seen in competitive Valorant",
        ]
        cricket_ideas = [
            f"top 3 moments from the latest India series",
            "Kohli at his peak vs Kohli now — the data actually surprises you",
            "WHY India's bowling lineup in 2026 is terrifying",
        ]
        tech_ideas = [
            "I asked Claude to write my entire day and here's what happened",
            "5 AI tools that actually changed how I work (not clickbait)",
        ]
        bangalore_ideas = [
            "day in my life in Bangalore — from traffic hell to gaming night",
            "Bangalore startup culture is unhinged and I love it",
        ]
        all_ideas = gaming_ideas + cricket_ideas + tech_ideas + bangalore_ideas
        # Boost topics matching current trends
        trending_ideas = [i for i in all_ideas
                          if any(t.lower() in i.lower() for t in trends)]
        if trending_ideas:
            return (trending_ideas + all_ideas)[:4]
        random.shuffle(all_ideas)
        return all_ideas[:4]

    def _load_cached(self, today: str) -> Optional[dict]:
        try:
            raw = memory.get(_KV_KEY, "")
            if not raw:
                return None
            data = json.loads(raw)
            if data.get("date") != today:
                return None
            return data
        except Exception:
            return None

    def _save_cached(self, today: str, data: dict) -> None:
        memory.set(_KV_KEY, json.dumps(data))


idea_factory = IdeaFactory()
