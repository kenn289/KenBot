"""
KenBot OS — Content Scheduler
APScheduler-based cron jobs for X and YouTube.
Schedule:
  - 3 tweets/hour, 7am–11pm IST → 51 tweets/day
    :00 = hype/hot take  :20 = content/topic  :40 = crack joke/meme
  - Engagement (like + comment For You feed) every 30 min, 8am–11pm IST
  - Reply sniper every 2 hours, 9am–9pm IST
  - Threads 3x/week: Mon 8pm, Wed 8pm, Sat 11am IST
  - 4 YT Shorts/day at 10am, 1pm, 5pm, 8pm IST
  - Daily ideas 7am IST, Daily briefing 8:30am IST
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

from channels.twitter.poster import twitter
from channels.twitter.x_engagement import x_engagement
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
        # ── 3 tweets per hour, 7am–11pm IST ───────────────────────────────
        # :00 = hype/hot take tweet     :20 = content/topic tweet
        # :40 = crack joke / meme tweet
        active_hours = list(range(7, 24))  # 7am to 11pm IST (17 hours = 51 tweets/day)
        for hour in active_hours:
            self.scheduler.add_job(
                func=self._post_shitpost,
                trigger=CronTrigger(hour=hour, minute=0, timezone=TZ),
                id=f"shitpost_{hour:02d}00",
                name=f"HypeTweet {hour}:00",
                replace_existing=True,
                misfire_grace_time=300,
            )
            self.scheduler.add_job(
                func=self._post_tweet,
                trigger=CronTrigger(hour=hour, minute=20, timezone=TZ),
                id=f"tweet_{hour:02d}20",
                name=f"ContentTweet {hour}:20",
                replace_existing=True,
                misfire_grace_time=300,
            )
            self.scheduler.add_job(
                func=self._post_shitpost,
                trigger=CronTrigger(hour=hour, minute=40, timezone=TZ),
                id=f"joke_{hour:02d}40",
                name=f"JokeTweet {hour}:40",
                replace_existing=True,
                misfire_grace_time=300,
            )

        # ── Engagement every 30 min, 8am–11pm IST ────────────────────────
        # :10 and :40 — like + comment on For You feed
        for hour in range(8, 24):
            for minute in [10, 40]:
                self.scheduler.add_job(
                    func=self._run_engagement,
                    trigger=CronTrigger(hour=hour, minute=minute, timezone=TZ),
                    id=f"engage_{hour:02d}{minute:02d}",
                    name=f"Engage {hour}:{minute:02d}",
                    replace_existing=True,
                    misfire_grace_time=300,
                )

        # ── Threads 3x/week — Mon 8pm, Wed 8pm, Sat 11am IST ─────────────
        for job_id, dow, hour, minute in [
            ("thread_mon", "mon", 20, 0),
            ("thread_wed", "wed", 20, 0),
            ("thread_sat", "sat", 11, 0),
        ]:
            self.scheduler.add_job(
                func=self._post_weekly_thread,
                trigger=CronTrigger(day_of_week=dow, hour=hour, minute=minute, timezone=TZ),
                id=job_id,
                name=f"Thread {dow} {hour}:00",
                replace_existing=True,
                misfire_grace_time=1800,
            )

        # ── Reply sniper every 2 hours, 9am–9pm IST ──────────────────────
        for hour in range(9, 22, 2):
            self.scheduler.add_job(
                func=self._run_reply_sniper,
                trigger=CronTrigger(hour=hour, minute=5, timezone=TZ),
                id=f"reply_sniper_{hour:02d}",
                name=f"ReplySniper {hour}:05",
                replace_existing=True,
                misfire_grace_time=600,
            )

        # ── YouTube: 4 drafts/day ───────────────────────────────────────────
        for job_id, job_name, hour in [
            ("yt_draft_morning",   "YouTube Draft Morning",   10),
            ("yt_draft_afternoon", "YouTube Draft Afternoon", 13),
            ("yt_draft_evening",   "YouTube Draft Evening",   17),
            ("yt_draft_night",     "YouTube Draft Night",     20),
        ]:
            self.scheduler.add_job(
                func=self._generate_yt_draft,
                trigger=CronTrigger(hour=hour, minute=0, timezone=TZ),
                id=job_id,
                name=job_name,
                replace_existing=True,
                misfire_grace_time=7200,  # 2-hour window — catch up if bot starts late
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
            # If no YT upload has happened today yet, fire one now (30-sec delay
            # so the scheduler is fully ready before the job runs).
            try:
                uploads_today = yt_uploader._uploads_today()
                if uploads_today == 0:
                    from apscheduler.triggers.date import DateTrigger
                    import datetime as _dt
                    run_at = _dt.datetime.now(tz=TZ) + _dt.timedelta(seconds=30)
                    self.scheduler.add_job(
                        func=self._generate_yt_draft,
                        trigger=DateTrigger(run_date=run_at, timezone=TZ),
                        id="yt_startup",
                        name="YT Startup Upload",
                        replace_existing=True,
                    )
                    logger.info("YT startup job queued (no uploads yet today)")
            except Exception as exc:
                logger.debug(f"YT startup check failed: {exc}")

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

    def _run_engagement(self) -> None:
        logger.info("⏰ Feed engagement running (like + reply)…")
        try:
            result = x_engagement.run_engagement()
            logger.info(f"Engagement done — liked: {result.get('liked',0)}, replied: {result.get('replied',0)}")
        except Exception as exc:
            logger.error(f"Engagement job failed: {exc}")

    def _post_shitpost(self) -> None:
        logger.info("⏰ Shitpost job running…")
        try:
            result = x_engagement.post_shitpost()
            if result:
                logger.info(f"Shitpost posted: {result}")
        except Exception as exc:
            logger.error(f"Shitpost job failed: {exc}")

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
