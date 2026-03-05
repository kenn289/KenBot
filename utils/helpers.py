"""
Ken ClawdBot — General Helpers
"""
from __future__ import annotations

import hashlib
import re
import time
from functools import wraps
from typing import Any, Callable, TypeVar

from tenacity import retry, stop_after_attempt, wait_exponential

T = TypeVar("T")


def rate_limited(calls_per_minute: int = 10):
    """Simple in-process rate limiter decorator."""
    min_interval = 60.0 / calls_per_minute
    last_call: dict[str, float] = {}

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> T:
            key = func.__qualname__
            elapsed = time.monotonic() - last_call.get(key, 0)
            if elapsed < min_interval:
                time.sleep(min_interval - elapsed)
            last_call[key] = time.monotonic()
            return func(*args, **kwargs)

        return wrapper

    return decorator


def retry_api(max_attempts: int = 3, wait_min: float = 2, wait_max: float = 10):
    """Decorator: exponential backoff retry for API calls."""
    return retry(
        stop=stop_after_attempt(max_attempts),
        wait=wait_exponential(multiplier=1, min=wait_min, max=wait_max),
        reraise=True,
    )


def truncate(text: str, max_chars: int = 280, suffix: str = "…") -> str:
    """Truncate text to max_chars (e.g., Twitter limit)."""
    if len(text) <= max_chars:
        return text
    return text[: max_chars - len(suffix)].rstrip() + suffix


def fingerprint(text: str) -> str:
    """Stable short hash for deduplication."""
    return hashlib.md5(text.strip().lower().encode()).hexdigest()[:12]


def clean_for_tweet(text: str) -> str:
    """Strip markdown, normalize whitespace for tweet posting."""
    text = re.sub(r"\*\*(.+?)\*\*", r"\1", text)  # bold
    text = re.sub(r"\*(.+?)\*", r"\1", text)       # italic
    text = re.sub(r"#{1,6}\s*", "", text)           # headings
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text) # links
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def split_into_thread(text: str, limit: int = 270) -> list[str]:
    """
    Split long text into tweet-thread list.
    Each chunk ≤ limit chars, broken on sentence boundaries where possible.
    """
    sentences = re.split(r"(?<=[.!?])\s+", text)
    thread: list[str] = []
    current = ""

    for sentence in sentences:
        if len(current) + len(sentence) + 1 <= limit:
            current = f"{current} {sentence}".strip()
        else:
            if current:
                thread.append(current)
            # If single sentence is too long, hard-cut it
            while len(sentence) > limit:
                thread.append(sentence[:limit])
                sentence = sentence[limit:]
            current = sentence

    if current:
        thread.append(current)

    return thread
