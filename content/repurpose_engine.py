"""
KenBot OS — Content Repurpose Engine
Converts content across platforms:
  YouTube Shorts → text tweet
  YouTube Shorts → thread seed
  Tweet → video script hook
  Thread → summary tweet
"""
from __future__ import annotations

import json
import textwrap
from typing import Optional

from utils.logger import logger


class RepurposeEngine:
    """
    Takes content from one format and adapts it to another.
    All transformations are deterministic (no AI needed for basic repurposing).
    Pass result to ai_engine for tone-polish when needed.
    """

    def yt_to_tweet(self, title: str, description: str = "") -> str:
        """Convert a YouTube Short title/description into a punchy tweet."""
        # Strip hashtags and clean up
        clean = title.replace("#Shorts", "").replace("#", "").strip()
        # Truncate to tweet-friendly length
        if len(clean) > 200:
            clean = clean[:197] + "..."
        return f"{clean}\n\n(full breakdown on YouTube ↗)"

    def yt_to_thread(self, title: str, script: str = "") -> list[str]:
        """Convert a YouTube Short into a tweet thread seed."""
        tweets = [f"made a Short on this but there's more to say 🧵\n\ntopic: {title}"]
        if script:
            # Split script into thread chunks
            chunks = textwrap.wrap(script, 240)
            for i, chunk in enumerate(chunks[:6], 1):
                tweets.append(f"{i}/ {chunk}")
        else:
            tweets.append("1/ the short version is up but the full context needs a thread...")
            tweets.append("2/ [expand with AI or manually]")
        tweets.append(f"full Short: link in bio 🔗")
        return tweets

    def tweet_to_reel(self, tweet_text: str) -> dict:
        """
        Convert a viral tweet into a Reel/TikTok concept.
        Returns a video concept dict.
        """
        return {
            "hook":        tweet_text[:80],
            "format":      "text-on-screen with reaction audio",
            "hook_type":   "POV / hot take",
            "voiceover":   tweet_text,
            "caption":     tweet_text,
            "platform":    ["instagram_reels", "tiktok", "youtube_shorts"],
        }

    def thread_to_carousel(self, tweets: list[str]) -> dict:
        """Convert a tweet thread into a social media carousel."""
        slides = []
        for i, tweet in enumerate(tweets, 1):
            slides.append({
                "slide": i,
                "text":  tweet,
                "style": "dark bg, white text, Ken's handle bottom right",
            })
        return {
            "format":  "carousel",
            "slides":  slides,
            "caption": tweets[0][:100],
            "platforms": ["instagram", "linkedin"],
        }

    def thread_to_video(self, tweets: list[str], title: str = "") -> dict:
        """Convert a thread into a YouTube/Reel video script."""
        script_lines = []
        for tweet in tweets[1:7]:  # skip opener, take body
            # Clean numbering
            clean = tweet.lstrip("0123456789/. ").strip()
            script_lines.append(clean)
        return {
            "title":   title or tweets[0][:80] if tweets else "KenBot video",
            "script":  " ".join(script_lines),
            "hook":    tweets[0] if tweets else "",
            "format":  "talking-head or text-on-screen",
            "target":  "youtube_shorts",
        }

    def batch_repurpose(self, content: dict) -> dict:
        """
        Repurpose a single piece of content to ALL formats.
        Input: {type, title, body, platform}
        """
        ctype = content.get("type", "tweet")
        body = content.get("body", "")
        title = content.get("title", body[:60])

        outputs: dict = {}
        if ctype in ("youtube_short", "video"):
            outputs["tweet"] = self.yt_to_tweet(title, body)
            outputs["thread_seeds"] = self.yt_to_thread(title, body)
            outputs["reel_concept"] = self.tweet_to_reel(title)
        elif ctype in ("tweet",):
            outputs["reel_concept"] = self.tweet_to_reel(body)
            outputs["video_script"] = self.thread_to_video([body], title)
        elif ctype in ("thread",):
            tweets = content.get("tweets", [body])
            outputs["carousel"] = self.thread_to_carousel(tweets)
            outputs["video_script"] = self.thread_to_video(tweets, title)
            outputs["summary_tweet"] = tweets[0] if tweets else body[:240]

        return outputs


repurpose_engine = RepurposeEngine()
