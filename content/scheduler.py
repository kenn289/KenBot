"""
Ken ClawdBot — Content Scheduler
APScheduler-based cron jobs for X and YouTube.
Conservative scheduling — won't exhaust free tier quotas.
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

    def _register_jobs(self) -> None:
        # ── Twitter: 5 tweets/day ──────────────────────────────────────────
        for job_id, job_name, hour, minute in [
            ("tweet_0930", "Tweet 9:30am",   9, 30),
            ("tweet_1200", "Tweet 12:00pm", 12,  0),
            ("tweet_1500", "Tweet 3:00pm",  15,  0),
            ("tweet_1900", "Tweet 7:00pm",  19,  0),
            ("tweet_2200", "Tweet 10:00pm", 22,  0),
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

        logger.info("Content scheduler jobs registered ✓")

    def start(self) -> None:
        if not self.scheduler.running:
            self.scheduler.start()
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
        logger.info("⏰ YouTube draft generation running…")
        try:
            package = yt_content.generate_video_package(duration_minutes=5)
            logger.info(f"YT draft saved to: {package['output_dir']}")
        except Exception as exc:
            logger.error(f"YT draft job failed: {exc}")

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
                "next_run": str(job.next_run_time),
            })
        return jobs


# Singleton
scheduler = ContentScheduler()
