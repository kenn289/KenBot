"""
KenBot OS — Meme Generator
Generates text-layer meme data. Uses PIL to render if available,
otherwise returns structured JSON for the caller to render.
Supported formats: drake, two_buttons, expanding_brain, reaction.
"""
from __future__ import annotations

import json
import os
import random
from pathlib import Path
from typing import Optional

from core.content_brain import content_brain
from utils.logger import logger

OUTPUT_DIR = Path("output") / "memes"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


class MemeGenerator:
    """
    Generates meme content. When PIL is available, renders the image.
    Always returns a dict with the text layers so callers can post
    text-only fallbacks if image rendering fails.
    """

    def generate(
        self,
        situation: str = "",
        format_override: Optional[str] = None,
    ) -> dict:
        """
        Returns {format, path (if rendered), text_layers, fallback_tweet}.
        """
        meme_data = content_brain.meme_idea(situation)
        fmt = format_override or meme_data.get("format", "drake")

        result = {
            "format":         fmt,
            "text_layers":    meme_data,
            "path":           None,
            "fallback_tweet": self._to_tweet(meme_data),
            "rendered":       False,
        }

        try:
            path = self._render(fmt, meme_data)
            if path:
                result["path"] = str(path)
                result["rendered"] = True
        except Exception as e:
            logger.debug(f"Meme render failed (PIL not available or template missing): {e}")

        return result

    def random_meme_tweet(self) -> str:
        """Generate a tweet-friendly text-only meme."""
        meme_data = content_brain.meme_idea()
        return self._to_tweet(meme_data)

    # ── Internal ──────────────────────────────────────────────────────────

    def _to_tweet(self, meme_data: dict) -> str:
        fmt = meme_data.get("format", "")
        if fmt == "drake":
            return (
                f"❌ {meme_data.get('top', 'bad choice')}\n"
                f"✅ {meme_data.get('bottom', 'good choice')}"
            )
        if fmt == "two_buttons":
            return (
                f"{meme_data.get('caption', 'me at 2am')}\n\n"
                f"[ {meme_data.get('left', 'option A')} ] vs [ {meme_data.get('right', 'option B')} ]"
            )
        if fmt == "expanding_brain":
            panels = meme_data.get("panels", [])
            return "\n".join(
                f"{'🔥' * (i+1) } {p}" for i, p in enumerate(panels)
            )
        return json.dumps(meme_data)

    def _render(self, fmt: str, data: dict) -> Optional[Path]:
        """Render image if PIL available. Returns path or None."""
        try:
            from PIL import Image, ImageDraw, ImageFont  # optional dep

            W, H = 800, 500
            img = Image.new("RGB", (W, H), "#1a1a2e")
            draw = ImageDraw.Draw(img)

            try:
                font = ImageFont.truetype("arial.ttf", 28)
                small = ImageFont.truetype("arial.ttf", 20)
            except Exception:
                font = ImageFont.load_default()
                small = font

            if fmt == "drake":
                draw.text((20, 20),  "❌", fill="#e94560", font=font)
                draw.text((60, 20),  data.get("top", ""),    fill="white", font=font)
                draw.text((20, 260), "✅", fill="#4ecca3",  font=font)
                draw.text((60, 260), data.get("bottom", ""), fill="white", font=font)
            elif fmt == "two_buttons":
                draw.text((20, 20),   data.get("caption", ""), fill="#e94560", font=font)
                draw.text((20, 150),  data.get("left", ""),    fill="white",   font=font)
                draw.text((420, 150), data.get("right", ""),   fill="white",   font=font)
                draw.text((350, 350), "??",                    fill="#ffd700",  font=font)
            elif fmt == "expanding_brain":
                panels = data.get("panels", [])
                y = 20
                for i, panel in enumerate(panels[:4]):
                    color = ["#555", "#888", "#bbb", "#fff"][min(i, 3)]
                    draw.text((20, y), f"{'🔥'*(i+1)} {panel}", fill=color, font=small)
                    y += 100

            ts = __import__("time").strftime("%Y%m%d_%H%M%S")
            path = OUTPUT_DIR / f"meme_{fmt}_{ts}.png"
            img.save(path)
            logger.info(f"Meme rendered: {path}")
            return path
        except ImportError:
            return None


meme_generator = MemeGenerator()
