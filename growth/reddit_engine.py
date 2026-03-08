"""
KenBot OS — Reddit Engine
Posts insights, comments on trending posts, and answers questions
on Reddit to drive traffic to Kenneth's Twitter and YouTube.
"""
from __future__ import annotations

import json
import random
import time
from typing import Optional

from content.reddit_miner import reddit_miner, _HEADERS
from memory.store import memory
from utils.logger import logger

_POST_LOG_KEY = "reddit_post_log"

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
    Currently read-only (commenting requires Reddit API auth which is optional).
    Provides scripts + strategies for Kenneth to manually post.
    """

    def generate_comment(self, post_title: str, subreddit: str = "general") -> str:
        """
        Generate a short, genuine Reddit comment using Claude + live Tavily context.
        Reads the post, thinks about what's actually interesting, and responds as Kenneth.
        """
        try:
            from core.ai_engine import ken_ai
            from core.news_fetcher import news_fetcher as _nf
            from config.ken_personality import IDENTITY

            # Pull live context so the comment is factually grounded
            live_ctx = ""
            try:
                live_ctx = _nf.get_news_context_for_claude(post_title)
            except Exception:
                pass

            ctx_block = ""
            if live_ctx:
                ctx_block = f"\n\nLIVE CONTEXT:\n{live_ctx}\nUse this to make your comment accurate and current."

            niche = _COMMENT_SUBS.get(subreddit, "general")
            system = (
                f"{IDENTITY}\n\n"
                f"You are commenting on a Reddit post in r/{subreddit} (topic: {niche}). "
                "Write a genuine, short comment — 1-3 sentences max. "
                "Add real value: a specific observation, a counter-point, or something the thread is missing. "
                "Sound like a person who actually knows this topic, not someone promoting themselves. "
                "Lowercase/casual but genuine. No fluff. No self-promotion. No 'great post!'.\n"
                "Output ONLY the comment text, nothing else."
                + ctx_block
            )
            comment = ken_ai._call(
                system,
                f"Reddit post title: {post_title}\n\nWrite your comment:",
                model="claude-haiku-4-5",
                max_tokens=120,
                use_cache=False,
            )
            return comment[:300]
        except Exception as e:
            logger.warning(f"Reddit comment generation failed: {e}")
            # Fallback to template
            import random
            style = random.choice(_COMMENT_STYLES)
            niche = _COMMENT_SUBS.get(subreddit, "general")
            return style.format(
                adjective=random.choice(["underrated", "interesting", "overlooked"]),
                extra=self._get_insight(niche, post_title),
                counter=self._get_counter(niche),
                observation=self._get_observation(niche),
                topic=post_title.split()[:3][0] if post_title else "this",
            )[:300]

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
