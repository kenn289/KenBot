from __future__ import annotations

import json
import time
from datetime import datetime
from typing import Optional

from channels.twitter.poster import twitter
from config.settings import settings
from growth.reddit_engine import reddit_engine
from memory.store import memory
from utils.logger import logger

_PROMO_HISTORY_KEY = "promo:attempt_history"
_PROMO_HISTORY_MAX = 200


class PromotionManager:
    """
    Controlled self-promotion manager for repo awareness.
    Safety controls:
      - explicit enable flag
      - subreddit allowlist
      - per-platform cooldowns
      - daily caps
      - never repost same Reddit thread
    """

    def _repo_url(self) -> str:
        return (settings.promo_repo_url or "").strip()

    def _enabled(self) -> bool:
        return bool(settings.promo_enabled and self._repo_url())

    def _allowlist(self) -> list[str]:
        raw = settings.promo_reddit_allowlist_raw or ""
        allow = [item.strip().lower() for item in raw.split(",") if item.strip()]
        if "technology" not in allow:
            allow.append("technology")
        return allow

    @staticmethod
    def _today_key(prefix: str) -> str:
        return f"{prefix}:{datetime.utcnow().date().isoformat()}"

    @staticmethod
    def _get_int(key: str) -> int:
        try:
            return int(memory.get(key, "0") or "0")
        except Exception:
            return 0

    def _inc(self, key: str, n: int = 1) -> None:
        memory.set(key, str(self._get_int(key) + n))

    @staticmethod
    def _load_history() -> list[dict]:
        try:
            raw = memory.get(_PROMO_HISTORY_KEY, "[]")
            data = json.loads(raw)
            return data if isinstance(data, list) else []
        except Exception:
            return []

    @staticmethod
    def _save_history(items: list[dict]) -> None:
        memory.set(_PROMO_HISTORY_KEY, json.dumps(items[-_PROMO_HISTORY_MAX:]))

    def _record_attempt(self, platform: str, ok: bool, reason: str = "", details: Optional[dict] = None) -> None:
        rows = self._load_history()
        row = {
            "ts": int(time.time()),
            "iso": datetime.utcnow().isoformat(),
            "platform": platform,
            "ok": bool(ok),
            "reason": reason,
            "details": details or {},
        }
        rows.append(row)
        self._save_history(rows)

    def _is_on_cooldown(self, key: str, cooldown_minutes: int) -> bool:
        try:
            last = int(memory.get(key, "0") or "0")
        except Exception:
            last = 0
        if not last:
            return False
        return (int(time.time()) - last) < (cooldown_minutes * 60)

    @staticmethod
    def _can_attach_repo_link(title: str, subreddit: str) -> bool:
        text = f"{subreddit} {title}".lower()
        triggers = (
            "open source", "opensource", "github", "project", "tool", "automation",
            "bot", "showcase", "feedback", "how", "build", "made", "script",
            "python", "ai", "agent",
        )
        return any(token in text for token in triggers)

    def _promo_tweet_text(self, custom_text: Optional[str] = None) -> str:
        if custom_text and custom_text.strip():
            return custom_text.strip()[:270]
        repo = self._repo_url()
        return (
            "open-sourced my autonomous personal AI stack: whatsapp + x + reddit + youtube in one system. "
            f"repo: {repo} "
            "if you build agentic systems, clone it and make it yours."
        )

    def run_x_promo(self, custom_text: Optional[str] = None) -> dict:
        if not self._enabled():
            out = {"ok": False, "error": "promo_disabled_or_repo_missing"}
            self._record_attempt("x", ok=False, reason=out["error"])
            return out

        day_key = self._today_key("promo:x_count")
        if self._get_int(day_key) >= max(0, int(settings.promo_x_daily_cap)):
            out = {"ok": False, "error": "x_daily_cap_reached"}
            self._record_attempt("x", ok=False, reason=out["error"])
            return out

        if self._is_on_cooldown("promo:x_last_ts", int(settings.promo_x_cooldown_minutes)):
            out = {"ok": False, "error": "x_cooldown_active"}
            self._record_attempt("x", ok=False, reason=out["error"])
            return out

        text = self._promo_tweet_text(custom_text)
        tweet_id = twitter.post_tweet(text)
        if not tweet_id:
            out = {"ok": False, "error": "x_post_failed"}
            self._record_attempt("x", ok=False, reason=out["error"])
            return out

        self._inc(day_key)
        memory.set("promo:x_last_ts", str(int(time.time())))
        out = {"ok": True, "tweet_id": tweet_id, "text": text}
        self._record_attempt("x", ok=True, reason="posted", details={"tweet_id": tweet_id, "text": text[:140]})
        return out

    def run_reddit_promo(self, max_comments: int = 1, force_link: bool = False) -> dict:
        if not self._enabled():
            out = {"ok": False, "error": "promo_disabled_or_repo_missing", "posted": 0, "items": []}
            self._record_attempt("reddit", ok=False, reason=out["error"])
            return out

        day_key = self._today_key("promo:reddit_count")
        daily_cap = max(0, int(settings.promo_reddit_daily_cap))
        if self._get_int(day_key) >= daily_cap:
            out = {"ok": False, "error": "reddit_daily_cap_reached", "posted": 0, "items": []}
            self._record_attempt("reddit", ok=False, reason=out["error"])
            return out

        if self._is_on_cooldown("promo:reddit_last_ts", int(settings.promo_reddit_cooldown_minutes)):
            out = {"ok": False, "error": "reddit_cooldown_active", "posted": 0, "items": []}
            self._record_attempt("reddit", ok=False, reason=out["error"])
            return out

        allow = set(self._allowlist())
        opportunities = sorted(
            reddit_engine.get_posting_opportunities(),
            key=lambda item: int(item.get("score", 0)),
            reverse=True,
        )

        posted = 0
        items: list[dict] = []
        skipped: list[dict] = []
        repo = self._repo_url()

        for item in opportunities:
            if posted >= max(1, max_comments):
                break
            if (self._get_int(day_key) + posted) >= daily_cap:
                break

            subreddit = str(item.get("subreddit", "")).strip().lower()
            if allow and subreddit not in allow:
                skipped.append({"subreddit": subreddit, "reason": "subreddit_not_allowlisted"})
                continue

            post_url = item.get("url", "")
            post_id = reddit_engine._post_id_from_url(post_url)
            if not post_id:
                skipped.append({"url": post_url, "reason": "invalid_post_id"})
                continue

            if memory.get(f"promo:reddit_posted:{post_id}", ""):
                skipped.append({"post_id": post_id, "reason": "already_promoted_here"})
                continue

            base_comment = str(item.get("comment", "") or "").strip()
            if not base_comment:
                skipped.append({"post_id": post_id, "reason": "empty_comment"})
                continue

            comment = base_comment
            if force_link or self._can_attach_repo_link(str(item.get("title", "")), subreddit):
                link_tail = f"\n\nif useful, i open-sourced a similar stack: {repo}"
                available = max(30, 300 - len(link_tail))
                comment = comment[:available].rstrip()
                comment = (comment + link_tail)[:300]

            comment_id = reddit_engine.post_comment(post_url, comment)
            if not comment_id:
                skipped.append({"post_id": post_id, "reason": "post_failed"})
                continue

            posted += 1
            memory.set(f"promo:reddit_posted:{post_id}", str(int(time.time())))
            items.append({
                "post_id": post_id,
                "comment_id": comment_id,
                "subreddit": subreddit,
                "url": post_url,
                "comment": comment,
            })

        if posted > 0:
            self._inc(day_key, posted)
            memory.set("promo:reddit_last_ts", str(int(time.time())))

        out = {
            "ok": posted > 0,
            "posted": posted,
            "items": items,
            "skipped": skipped,
            "allowlist": sorted(list(allow)),
        }
        self._record_attempt(
            "reddit",
            ok=bool(out["ok"]),
            reason="posted" if out["ok"] else "no_posted_items",
            details={
                "posted": posted,
                "skipped": len(skipped),
                "top_skip_reasons": [s.get("reason", "") for s in skipped[:5]],
                "allowlist": sorted(list(allow)),
            },
        )
        return out

    def run_campaign(
        self,
        do_x: bool = True,
        do_reddit: bool = True,
        max_reddit_comments: int = 1,
        force_reddit_link: bool = False,
    ) -> dict:
        result = {"ok": False, "x": None, "reddit": None}
        if do_x:
            result["x"] = self.run_x_promo()
        if do_reddit:
            result["reddit"] = self.run_reddit_promo(
                max_comments=max_reddit_comments,
                force_link=force_reddit_link,
            )

        result["ok"] = bool(
            (result.get("x") and result["x"].get("ok"))
            or (result.get("reddit") and result["reddit"].get("ok"))
        )
        return result

    def status(self) -> dict:
        allow = self._allowlist()
        x_count = self._get_int(self._today_key("promo:x_count"))
        reddit_count = self._get_int(self._today_key("promo:reddit_count"))
        return {
            "enabled": self._enabled(),
            "repo_url": self._repo_url(),
            "allowlist": allow,
            "x": {
                "today_count": x_count,
                "daily_cap": int(settings.promo_x_daily_cap),
                "cooldown_minutes": int(settings.promo_x_cooldown_minutes),
                "on_cooldown": self._is_on_cooldown("promo:x_last_ts", int(settings.promo_x_cooldown_minutes)),
            },
            "reddit": {
                "today_count": reddit_count,
                "daily_cap": int(settings.promo_reddit_daily_cap),
                "cooldown_minutes": int(settings.promo_reddit_cooldown_minutes),
                "on_cooldown": self._is_on_cooldown("promo:reddit_last_ts", int(settings.promo_reddit_cooldown_minutes)),
            },
        }

    def analytics(self, limit: int = 10) -> dict:
        rows = self._load_history()
        limit = max(1, min(int(limit), 50))
        recent = rows[-limit:]
        recent.reverse()
        return {
            "count": len(recent),
            "items": recent,
        }


promotion_manager = PromotionManager()
