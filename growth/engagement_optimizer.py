"""
KenBot OS — Engagement Optimizer
Reads analytics and recommends content strategy adjustments.
If cricket tweets outperform, increase cricket ratio, etc.
"""
from __future__ import annotations

from analytics.performance import analytics
from core.humor_engine import humor_engine
from utils.logger import logger


class EngagementOptimizer:
    """
    Reads from analytics + humor engine and produces strategy recommendations.
    Also adjusts the content pipeline weighting when called.
    """

    def get_recommendations(self) -> dict:
        """
        Returns a strategy recommendation dict with pillar weightings.
        """
        ts = analytics.twitter_summary(last_n=20)
        top_tweets = analytics.top_tweets(n=5, by="likes")
        best_humor = humor_engine.best_category()

        # Analyse what topics are in top tweets
        topic_counts: dict[str, int] = {}
        for t in top_tweets:
            topic = t.get("topic", "general")
            topic_counts[topic] = topic_counts.get(topic, 0) + t.get("likes", 0)

        best_topic = max(topic_counts, key=lambda k: topic_counts[k]) if topic_counts else "general"

        rec = {
            "best_performing_topic":    best_topic,
            "best_performing_humor":    best_humor,
            "avg_engagement_pct":       ts.get("avg_engagement_pct", 0),
            "recommendations": [],
        }

        # Generate human-readable strategy tips
        if topic_counts:
            rec["recommendations"].append(
                f"increase {best_topic} content — it's driving {topic_counts.get(best_topic, 0)} likes"
            )
        if best_humor != "general":
            rec["recommendations"].append(
                f"lean into {best_humor.replace('_', ' ')} humor — it's your top-performing style"
            )
        if ts.get("avg_engagement_pct", 0) < 1:
            rec["recommendations"].append(
                "engagement below 1% — try more polls and debate-style tweets"
            )
        if ts.get("total_rt", 0) < ts.get("total_likes", 0) / 10:
            rec["recommendations"].append(
                "low RT ratio — create more shareable takes and opinion threads"
            )
        if not rec["recommendations"]:
            rec["recommendations"].append("performance looks solid — maintain current cadence")

        return rec

    def format_briefing(self) -> str:
        rec = self.get_recommendations()
        lines = ["*content strategy recommendations:*\n"]
        for r in rec.get("recommendations", []):
            lines.append(f"• {r}")
        lines.append(f"\nbest topic: {rec.get('best_performing_topic', 'general')}")
        lines.append(f"best humor style: {rec.get('best_performing_humor', 'n/a')}")
        return "\n".join(lines)

    def adjust_content_weights(self) -> dict:
        """
        Returns a weighting dict the scheduler can use to pick topics.
        Higher weight = pick this topic more often.
        """
        rec = self.get_recommendations()
        best = rec.get("best_performing_topic", "general")
        weights: dict[str, float] = {
            "gaming":    1.0,
            "cricket":   1.0,
            "tech":      1.0,
            "bangalore": 1.0,
            "general":   0.8,
        }
        # Boost the best performing topic
        for k in weights:
            if best.lower() in k:
                weights[k] = 2.0
                break
        return weights


engagement_optimizer = EngagementOptimizer()
