"""
KenBot OS — Humor Engine
Tracks which humor styles perform best and surfaces winning patterns
for the content brain to lean on. Fully offline — reads from analytics KV.
"""
from __future__ import annotations

import json
import random
from collections import defaultdict
from datetime import datetime
from typing import Optional

from memory.store import memory
from utils.logger import logger

_KV_KEY = "humor_patterns"

# Broad humor categories Ken uses
HUMOR_CATEGORIES = [
    "self_deprecating",    # laughing at himself
    "dry_observation",     # deadpan takes on life
    "sports_roast",        # clowning teams/players (affectionately)
    "gaming_pain",         # every gamer knows this feeling
    "bangalore_life",      # hyper-local relatable
    "tech_satire",         # startup culture, AI nonsense
    "generational",        # millennials vs gen z, parent logic
    "understatement",      # "valorant ranked is slightly stressful"
    "absurdist",           # random escalating nonsense
]


class HumorEngine:
    """
    Tracks humor performance metrics and surfaces the best-performing styles.
    Call `record_performance(pattern, metrics)` after each post.
    Call `top_patterns(n)` to get the n best-performing humor seeds.
    """

    def record_performance(
        self,
        category: str,
        content_snippet: str,
        *,
        likes: int = 0,
        retweets: int = 0,
        comments: int = 0,
        platform: str = "twitter",
    ) -> None:
        patterns = self._load()
        key = category.lower()
        if key not in patterns:
            patterns[key] = {
                "category": key,
                "total_posts": 0,
                "total_likes": 0,
                "total_rt": 0,
                "total_comments": 0,
                "engagement_score": 0.0,
                "recent": [],
            }
        p = patterns[key]
        p["total_posts"]    += 1
        p["total_likes"]    += likes
        p["total_rt"]       += retweets
        p["total_comments"] += comments
        # Weighted score: RT=3x, comment=2x, like=1x
        score = (likes + retweets * 3 + comments * 2)
        p["engagement_score"] = (
            (p["engagement_score"] * (p["total_posts"] - 1) + score) / p["total_posts"]
        )
        p["recent"] = ([{"snippet": content_snippet[:80], "score": score, "platform": platform,
                          "ts": datetime.utcnow().isoformat()}]
                        + p["recent"])[:10]
        self._save(patterns)
        logger.debug(f"Humor pattern tracked [{key}] score={score}")

    def top_patterns(self, n: int = 3) -> list[dict]:
        patterns = self._load()
        sorted_p = sorted(patterns.values(), key=lambda x: x.get("engagement_score", 0), reverse=True)
        return sorted_p[:n]

    def best_category(self) -> str:
        top = self.top_patterns(1)
        if top:
            return top[0]["category"]
        return random.choice(HUMOR_CATEGORIES)

    def performance_summary(self) -> str:
        patterns = self._load()
        if not patterns:
            return "no humor data yet — post more content"
        lines = []
        for cat, p in sorted(patterns.items(), key=lambda x: x[1].get("engagement_score", 0), reverse=True):
            lines.append(
                f"  {cat}: {p['total_posts']} posts, "
                f"avg score {p['engagement_score']:.1f} "
                f"({p['total_likes']} likes, {p['total_rt']} RTs)"
            )
        return "humor pattern leaderboard:\n" + "\n".join(lines)

    def _load(self) -> dict:
        try:
            return json.loads(memory.get(_KV_KEY, "{}"))
        except Exception:
            return {}

    def _save(self, data: dict) -> None:
        memory.set(_KV_KEY, json.dumps(data))


humor_engine = HumorEngine()
