"""
KenBot OS — Content Scheduler
APScheduler-based cron jobs for X and YouTube.
Schedule:
  - 8 tweets/day at 8:00, 9:30, 12:00, 14:00, 15:30, 19:00, 21:00, 22:30 IST
  - 2 YT Shorts/day at 10:00 and 16:00 IST
  - Weekly thread Saturday 11am IST
  - Daily briefing to Kenneth at 8:30am IST
  - Influencer reply sniper at 10:00, 15:00, 20:00 IST
  - Daily idea generation at 7:00am IST
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from channels.twitter.poster import twitter
from channels.youtube.content_gen import yt_content
from channels.youtube.uploader import yt_uploader
from config.settings import settings
from core.health_monitor import health_monitor
from utils.logger import logger

TZ = pytz.timezone(settings.timezone)


class ContentScheduler:
    """
    Manages all scheduled posting jobs.
    Schedule:
      - 5 tweets/day at 9:30, 12:00, 15:00, 19:00, 22:00 IST
      - 1 thread/week Saturday 11am IST
      - 2 YouTube drafts/day at 10:00 and 16:00 IST
    """

    def __init__(self) -> None:
        self.scheduler = BackgroundScheduler(timezone=TZ)
        self._register_jobs()
        self.start()

    def _register_jobs(self) -> None:
        # ── Twitter: 8 tweets/day ──────────────────────────────────────────
        for job_id, job_name, hour, minute in [
            ("tweet_0800", "Tweet 8:00am",    8,  0),
            ("tweet_0930", "Tweet 9:30am",    9, 30),
            ("tweet_1200", "Tweet 12:00pm",  12,  0),
            ("tweet_1400", "Tweet 2:00pm",   14,  0),
            ("tweet_1530", "Tweet 3:30pm",   15, 30),
            ("tweet_1900", "Tweet 7:00pm",   19,  0),
            ("tweet_2100", "Tweet 9:00pm",   21,  0),
            ("tweet_2230", "Tweet 10:30pm",  22, 30),
        ]:
            self.scheduler.add_job(
                func=self._post_tweet,
                trigger=CronTrigger(hour=hour, minute=minute, timezone=TZ),
                id=job_id,
                name=job_name,
                replace_existing=True,
                misfire_grace_time=600,
            )

        # Weekly thread — Saturday 11:00 AM IST
        self.scheduler.add_job(
            func=self._post_weekly_thread,
            trigger=CronTrigger(day_of_week="sat", hour=11, minute=0, timezone=TZ),
            id="weekly_thread",
            name="Weekend Thread",
            replace_existing=True,
            misfire_grace_time=1800,
        )

        # ── YouTube: 2 drafts/day ────────────────────────────────────────
        for job_id, job_name, hour in [
            ("yt_draft_am", "YouTube Draft AM", 10),
            ("yt_draft_pm", "YouTube Draft PM", 16),
        ]:
            self.scheduler.add_job(
                func=self._generate_yt_draft,
                trigger=CronTrigger(hour=hour, minute=0, timezone=TZ),
                id=job_id,
                name=job_name,
                replace_existing=True,
                misfire_grace_time=1800,
            )

        # Daily idea generation -- 7:00 AM IST
        self.scheduler.add_job(
            func=self._generate_daily_ideas,
            trigger=CronTrigger(hour=7, minute=0, timezone=TZ),
            id="daily_ideas",
            name="Daily Idea Generation",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Daily briefing to Kenneth -- 8:30 AM IST
        self.scheduler.add_job(
            func=self._send_daily_briefing,
            trigger=CronTrigger(hour=8, minute=30, timezone=TZ),
            id="daily_briefing",
            name="Daily Briefing",
            replace_existing=True,
            misfire_grace_time=3600,
        )

        # Influencer reply sniper -- 10am, 3pm, 8pm IST
        for job_id, job_name, hour in [
            ("reply_sniper_10", "Reply Sniper 10am", 10),
            ("reply_sniper_15", "Reply Sniper 3pm",  15),
            ("reply_sniper_20", "Reply Sniper 8pm",  20),
        ]:
            self.scheduler.add_job(
                func=self._run_reply_sniper,
                trigger=CronTrigger(hour=hour, minute=0, timezone=TZ),
                id=job_id,
                name=job_name,
                replace_existing=True,
                misfire_grace_time=600,
            )

        # ── Scheduler health ping: every 30 min ─────────────────────────────────────
        self.scheduler.add_job(
            func=lambda: health_monitor.ping("scheduler"),
            trigger=CronTrigger(minute="*/30", timezone=TZ),
            id="health_ping",
            name="Scheduler health ping",
            replace_existing=True,
            misfire_grace_time=300,
        )
        logger.info("Content scheduler jobs registered OK")

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
            health_monitor.ping("scheduler")
            logger.info("📅 Content scheduler started")

    def stop(self) -> None:
        if self.scheduler.running:
            self.scheduler.shutdown(wait=False)
            logger.info("Content scheduler stopped")

    # ── Job implementations ──────────────────────────────
    def _post_tweet(self) -> None:
        logger.info("⏰ Tweet job running…")
        try:
            tweet_id = twitter.post_content_tweet()
            if tweet_id:
                logger.info(f"Tweet posted: {tweet_id}")
        except Exception as exc:
            logger.error(f"Tweet job failed: {exc}")

    def _post_weekly_thread(self) -> None:
        logger.info("⏰ Weekly thread job running…")
        try:
            ids = twitter.post_content_thread(num_tweets=5)
            logger.info(f"Weekly thread posted: {len(ids)} tweets")
        except Exception as exc:
            logger.error(f"Weekly thread job failed: {exc}")

    def _generate_yt_draft(self) -> None:
        logger.info("YouTube Short generation + upload running...")
        try:
            package = yt_content.generate_video_package()
            if not package or not package.get("video_path"):
                logger.warning("YT generation returned no video")
                return
            video_id = yt_uploader.upload_package(package)
            if video_id:
                logger.info(f"YT Short live: https://youtu.be/{video_id}")
            else:
                logger.warning("YT upload returned no video ID")
        except Exception as exc:
            logger.error(f"YT job failed: {exc}")

    def _generate_daily_ideas(self) -> None:
        logger.info("Daily idea generation running...")
        try:
            from content.idea_factory import idea_factory
            idea_factory.get_daily_ideas(force_refresh=True)
            logger.info("Daily ideas generated")
        except Exception as exc:
            logger.error(f"Idea generation failed: {exc}")

    def _send_daily_briefing(self) -> None:
        logger.info("Daily briefing running...")
        try:
            from core.ai_engine import ken_ai
            from memory.store import memory
            briefing = ken_ai._daily_briefing()
            memory.queue_notification(briefing)
            logger.info("Daily briefing queued")
        except Exception as exc:
            logger.error(f"Daily briefing failed: {exc}")

    def _run_reply_sniper(self) -> None:
        logger.info("Reply sniper running...")
        try:
            from growth.influencer_reply_engine import influencer_reply_engine
            from memory.store import memory

            tweets = influencer_reply_engine.fetch_viral_tweets()
            if not tweets:
                logger.info("Reply sniper: no targets this cycle")
                return

            logger.info(f"Reply sniper: {len(tweets)} targets found")
            # Pick highest-liked tweet we haven't replied to yet
            for t in tweets:
                already = memory.get(f"replied_{t['id']}", "")
                if already:
                    continue

                reply = influencer_reply_engine.generate_reply_to(
                    t["text"], author=t.get("author", "")
                )
                if not reply:
                    continue

                result = twitter.post_tweet(reply)
                if result:
                    memory.set(f"replied_{t['id']}", "1")
                    logger.info(f"Reply sniper posted: {reply[:80]}")
                    memory.queue_notification(
                        f"\U0001f3af replied to @{t.get('author','?')}: {reply[:100]}"
                    )
                break  # one reply per sniper cycle to avoid spam
        except Exception as exc:
            logger.error(f"Reply sniper failed: {exc}")

    # ── Manual triggers ──────────────────────────────────
    def trigger_now(self, job_id: str) -> bool:
        """Manually trigger a job by ID."""
        job = self.scheduler.get_job(job_id)
        if not job:
            logger.warning(f"Job not found: {job_id}")
            return False
        job.func()
        return True

    def list_jobs(self) -> list[dict]:
        """Return all scheduled jobs with next run times."""
        jobs = []
        for job in self.scheduler.get_jobs():
            jobs.append({
                "id": job.id,
                "name": job.name,
                "next_run": str(getattr(job, "next_run_time", None)),
            })
        return jobs


# Singleton
scheduler = ContentScheduler()
