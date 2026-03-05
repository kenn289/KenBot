"""
Ken ClawdBot — Structured Logging
Rich console output + rotating file logs.
"""
import sys
from pathlib import Path
from loguru import logger
from config.settings import settings

# Remove default Loguru sink
logger.remove()

LOG_DIR = settings.root_dir / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

# ── Console ─────────────────────────────────
logger.add(
    sys.stdout,
    level=settings.log_level,
    format=(
        "<green>{time:HH:mm:ss}</green> | "
        "<level>{level: <8}</level> | "
        "<cyan>{name}</cyan>:<cyan>{line}</cyan> — "
        "<level>{message}</level>"
    ),
    colorize=True,
)

# ── Rolling file (10 MB, keep 7 days) ───────
logger.add(
    LOG_DIR / "ken_{time:YYYY-MM-DD}.log",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    compression="zip",
    format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{line} — {message}",
)

__all__ = ["logger"]
