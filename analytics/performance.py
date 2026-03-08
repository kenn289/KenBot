"""
KenBot OS — Analytics Engine
Tracks post performance across Twitter, YouTube.
Data stored in KV store. Provides summaries for Kenneth's daily briefing.
"""
from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Optional

from memory.store import memory
from utils.logger import logger

_KV_TWITTER  = "analytics:twitter"
_KV_YOUTUBE  = "analytics:youtube"
_KV_SUMMARY  = "analytics:last_summary"


class PerformanceAnalytics:
    """
    Records and queries post performance metrics.
    Twitter: impressions, likes, retweets, comments per tweet.
    YouTube: views, watch_time, likes per video.
    """

    # ── Twitter ───────────────────────────────────────────────────────────

    def record_tweet(
        self,
        tweet_id: str,
        text: str,
        *,
        topic: str = "",
        humor_category: str = "",
    ) -> None:
        """Call immediately after posting a tweet."""
        entry = {
            "tweet_id":       tweet_id,
            "text":           text[:140],
            "topic":          topic,
            "humor_category": humor_category,
            "posted_at":      datetime.utcnow().isoformat(),
            "impressions":    0,
            "likes":          0,
            "retweets":       0,
            "comments":       0,
            "engagement":     0.0,
        }
        tweets = self._load(_KV_TWITTER)
        tweets.append(entry)
        tweets = tweets[-500:]
        self._save(_KV_TWITTER, tweets)

    def update_tweet_metrics(
        self,
        tweet_id: str,
        *,
        impressions: int = 0,
        likes: int = 0,
        retweets: int = 0,
        comments: int = 0,
    ) -> None:
        tweets = self._load(_KV_TWITTER)
        for t in tweets:
            if t["tweet_id"] == tweet_id:
                t["impressions"] = impressions
                t["likes"]       = likes
                t["retweets"]    = retweets
                t["comments"]    = comments
                t["engagement"]  = (likes + retweets * 3 + comments * 2) / max(impressions, 1) * 100
                break
        self._save(_KV_TWITTER, tweets)

    # ── YouTube ───────────────────────────────────────────────────────────

    def record_video(
        self,
        video_id: str,
        title: str,
        *,
        topic: str = "",
    ) -> None:
        entry = {
            "video_id":   video_id,
            "title":      title[:100],
            "topic":      topic,
            "posted_at":  datetime.utcnow().isoformat(),
            "views":      0,
            "watch_time": 0,
            "likes":      0,
        }
        videos = self._load(_KV_YOUTUBE)
        videos.append(entry)
        videos = videos[-200:]
        self._save(_KV_YOUTUBE, videos)

    def update_video_metrics(
        self,
        video_id: str,
        *,
        views: int = 0,
        watch_time: int = 0,
        likes: int = 0,
    ) -> None:
        videos = self._load(_KV_YOUTUBE)
        for v in videos:
            if v["video_id"] == video_id:
                v["views"]      = views
                v["watch_time"] = watch_time
                v["likes"]      = likes
                break
        self._save(_KV_YOUTUBE, videos)

    # ── Summaries ─────────────────────────────────────────────────────────

    def twitter_summary(self, last_n: int = 10) -> dict:
        tweets = self._load(_KV_TWITTER)[-last_n:]
        if not tweets:
            return {"total": 0}
        total_likes = sum(t.get("likes", 0) for t in tweets)
        total_rt    = sum(t.get("retweets", 0) for t in tweets)
        total_impr  = sum(t.get("impressions", 0) for t in tweets)
        avg_eng     = sum(t.get("engagement", 0) for t in tweets) / len(tweets)
        return {
            "total":       len(tweets),
            "total_likes": total_likes,
            "total_rt":    total_rt,
            "total_impr":  total_impr,
            "avg_engagement_pct": round(avg_eng, 2),
        }

    def youtube_summary(self, last_n: int = 10) -> dict:
        videos = self._load(_KV_YOUTUBE)[-last_n:]
        if not videos:
            return {"total": 0}
        return {
            "total":      len(videos),
            "total_views": sum(v.get("views", 0) for v in videos),
            "total_likes": sum(v.get("likes", 0) for v in videos),
        }

    def top_tweets(self, n: int = 3, by: str = "likes") -> list[dict]:
        tweets = self._load(_KV_TWITTER)
        return sorted(tweets, key=lambda t: t.get(by, 0), reverse=True)[:n]

    def format_briefing(self) -> str:
        ts = self.twitter_summary()
        ys = self.youtube_summary()
        top = self.top_tweets(3)
        lines = [
            "*analytics update:*\n",
            f"*twitter (last 10 posts):*",
            f"  {ts.get('total', 0)} tweets | {ts.get('total_likes', 0)} likes | "
            f"{ts.get('total_rt', 0)} RTs | avg eng {ts.get('avg_engagement_pct', 0)}%",
        ]
        if top:
            lines.append("  top tweet: " + top[0].get("text", "")[:80])
        lines += [
            f"\n*youtube (last 10 Shorts):*",
            f"  {ys.get('total', 0)} videos | {ys.get('total_views', 0)} views | {ys.get('total_likes', 0)} likes",
        ]
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────────────────

    def _load(self, key: str) -> list:
        try:
            return json.loads(memory.get(key, "[]"))
        except Exception:
            return []

    def _save(self, key: str, data: list) -> None:
        memory.set(key, json.dumps(data))


analytics = PerformanceAnalytics()
