"""
Ken ClawdBot — Main Entry Point
Starts Flask API + Content Scheduler in one process.
The Node.js WhatsApp bot is started separately (see README).
"""
from __future__ import annotations

import sys
import signal
import threading
from pathlib import Path

# Ensure project root is on path
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings
from content.scheduler import scheduler
from api_bridge import run_api
from utils.logger import logger


def shutdown(signum, frame):
    logger.info("🛑 Shutdown signal received. Stopping scheduler…")
    scheduler.stop()
    sys.exit(0)


def main():
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    logger.info("════════════════════════════════════════")
    logger.info("  🐾  Ken ClawdBot  —  Starting up")
    logger.info("════════════════════════════════════════")
    logger.info(f"Timezone      : {settings.timezone}")
    logger.info(f"Flask port    : {settings.flask_port}")
    logger.info(f"Real groups   : {settings.ken_real_groups}")
    logger.info(f"Twitter ready : {bool(settings.twitter_api_key)}")

    # Start content scheduler in background thread
    scheduler.start()

    # Log next jobs
    for job in scheduler.list_jobs():
        logger.info(f"Scheduled: {job['name']} → next: {job['next_run']}")

    logger.info("════════════════════════════════════════")
    logger.info("  Start WhatsApp bot separately:")
    logger.info("  npm run whatsapp")
    logger.info("════════════════════════════════════════")

    # Run Flask (blocking)
    run_api(port=settings.flask_port)


if __name__ == "__main__":
    main()
