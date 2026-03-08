"""
KenBot OS — Health Monitor
Watches Flask, scheduler, and posting pipelines.
Sends Kenneth a WhatsApp alert when something breaks.
"""
from __future__ import annotations

import threading
import time
from datetime import datetime
from typing import Callable, Optional

from utils.logger import logger

_CHECKS: dict[str, dict] = {}
_ALERT_CB: Optional[Callable[[str], None]] = None  # set by api_bridge at startup
_lock = threading.Lock()


def register_alert_callback(fn: Callable[[str], None]) -> None:
    """api_bridge calls this so health monitor can DM Kenneth."""
    global _ALERT_CB
    _ALERT_CB = fn


class HealthMonitor:
    """
    Tracks service heartbeats and posts. Call `ping(service)` periodically.
    Background thread checks for gaps and calls alert callback.
    """

    def __init__(self, check_interval_seconds: int = 60) -> None:
        self._interval = check_interval_seconds
        self._heartbeats: dict[str, float] = {}
        self._thresholds: dict[str, int] = {}   # max seconds without ping
        self._alerted: set[str] = set()         # avoid spam
        self._thread: Optional[threading.Thread] = None
        self._running = False

    def register(self, service: str, max_silence_seconds: int = 300) -> None:
        """Register a service to monitor. Alert if silent for max_silence_seconds."""
        with _lock:
            self._thresholds[service] = max_silence_seconds
            self._heartbeats[service] = time.time()  # start healthy
        logger.debug(f"HealthMonitor: registered {service} (max silence {max_silence_seconds}s)")

    def ping(self, service: str) -> None:
        """Call this when the service does something successfully."""
        with _lock:
            self._heartbeats[service] = time.time()
            self._alerted.discard(service)   # reset alert state

    def record_post_success(self, platform: str, content: str = "") -> None:
        self.ping(f"post:{platform}")
        logger.info(f"HealthMonitor: {platform} post OK — {content[:60]}")

    def record_failure(self, service: str, error: str) -> None:
        logger.error(f"HealthMonitor: {service} FAILURE — {error}")
        self._maybe_alert(f"[KenBot] {service} failed: {error[:120]}")

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        logger.info("HealthMonitor started")

    def stop(self) -> None:
        self._running = False

    def status_report(self) -> dict:
        now = time.time()
        report = {}
        with _lock:
            for svc, last in self._heartbeats.items():
                age = now - last
                threshold = self._thresholds.get(svc, 300)
                report[svc] = {
                    "last_ping_ago_s": round(age),
                    "healthy": age < threshold,
                    "threshold_s": threshold,
                }
        return report

    # ── Internal ──────────────────────────────────────────────────────────

    def _loop(self) -> None:
        while self._running:
            try:
                self._check_all()
            except Exception as e:
                logger.error(f"HealthMonitor loop error: {e}")
            time.sleep(self._interval)

    def _check_all(self) -> None:
        now = time.time()
        with _lock:
            items = list(self._heartbeats.items())
            thresholds = dict(self._thresholds)
        for svc, last in items:
            age = now - last
            max_s = thresholds.get(svc, 300)
            if age > max_s and svc not in self._alerted:
                msg = f"[KenBot] {svc} hasn't responded in {int(age//60)}min — might be down"
                self._maybe_alert(msg)
                with _lock:
                    self._alerted.add(svc)

    def _maybe_alert(self, msg: str) -> None:
        logger.warning(msg)
        if _ALERT_CB:
            try:
                _ALERT_CB(msg)
            except Exception as e:
                logger.error(f"HealthMonitor alert callback failed: {e}")


health_monitor = HealthMonitor()
