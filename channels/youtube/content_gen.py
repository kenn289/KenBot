"""
Ken ClawdBot — YouTube Content Generator
Generates scripts, titles, descriptions using AI.
Creates simple text-based videos using Pillow + ffmpeg (fallback: script-only).
"""
from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path
from typing import Optional

from config.settings import settings
from core.ai_engine import ken_ai
from utils.logger import logger

MEDIA_DIR = settings.root_dir / "media"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)


class YouTubeContentGen:

    def generate_video_package(
        self,
        topic: Optional[str] = None,
        duration_minutes: int = 5,
    ) -> dict:
        """
        Full pipeline: pick topic → generate script → metadata → attempt video.
        Returns package dict with all assets.
        """
        if not topic:
            picked = ken_ai.pick_content_topic()
            topic = f"{picked.get('topic')}: {picked.get('angle')}"

        logger.info(f"📹 Generating YouTube package for: {topic}")

        # 1. Metadata
        metadata = ken_ai.generate_yt_title_and_description(topic)
        title = metadata.get("title", topic)
        description = metadata.get("description", "")
        tags = metadata.get("tags", [])

        # 2. Script
        script = ken_ai.generate_yt_script(topic, duration_minutes=duration_minutes)

        # 3. Save to file
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:50]
        out_dir = MEDIA_DIR / "youtube" / safe_title.replace(" ", "_")
        out_dir.mkdir(parents=True, exist_ok=True)

        script_path = out_dir / "script.txt"
        meta_path = out_dir / "metadata.json"

        script_path.write_text(script, encoding="utf-8")
        meta_path.write_text(
            json.dumps({"title": title, "description": description, "tags": tags}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )

        # 4. Attempt to create a simple title card video (Pillow + ffmpeg)
        video_path = self._try_create_title_card(out_dir, title, topic)

        package = {
            "topic": topic,
            "title": title,
            "description": description,
            "tags": tags,
            "script_path": str(script_path),
            "meta_path": str(meta_path),
            "video_path": str(video_path) if video_path else None,
            "output_dir": str(out_dir),
            "status": "ready" if video_path else "script_only",
        }

        logger.info(f"✅ Package ready: {out_dir}")
        return package

    def _try_create_title_card(self, out_dir: Path, title: str, topic: str) -> Optional[Path]:
        """
        Create a simple 10-second title-card mp4 using Pillow for the image
        and ffmpeg to turn it into a video.
        Returns path or None if creation fails.
        """
        try:
            from PIL import Image, ImageDraw, ImageFont

            img_path = out_dir / "title_card.png"
            video_path = out_dir / "title_card.mp4"

            # Create 1280×720 dark background
            img = Image.new("RGB", (1280, 720), color=(10, 10, 20))
            draw = ImageDraw.Draw(img)

            # Try to load a font, fall back to default
            try:
                font_title = ImageFont.truetype("arial.ttf", 56)
                font_sub = ImageFont.truetype("arial.ttf", 28)
            except OSError:
                font_title = ImageFont.load_default()
                font_sub = font_title

            # Wrap title
            wrapped = textwrap.wrap(title, width=30)
            y = 720 // 2 - (len(wrapped) * 60) // 2

            for line in wrapped:
                bbox = draw.textbbox((0, 0), line, font=font_title)
                text_w = bbox[2] - bbox[0]
                draw.text(((1280 - text_w) // 2, y), line, fill=(255, 255, 255), font=font_title)
                y += 70

            # Watermark
            draw.text((20, 690), "Ken — ClawdBot", fill=(100, 100, 120), font=font_sub)

            img.save(str(img_path))

            # ffmpeg: image → 10-second video (no audio)
            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-loop", "1",
                    "-i", str(img_path),
                    "-t", "10",
                    "-vf", "scale=1280:720",
                    "-r", "24",
                    "-c:v", "libx264",
                    "-pix_fmt", "yuv420p",
                    str(video_path),
                ],
                capture_output=True,
                timeout=60,
            )
            if result.returncode == 0:
                logger.info(f"Title card video created: {video_path}")
                return video_path
            else:
                logger.warning(f"ffmpeg failed: {result.stderr.decode()[:200]}")
                return None

        except Exception as exc:
            logger.warning(f"Video creation skipped ({exc}). Script-only mode.")
            return None


# Singleton
yt_content = YouTubeContentGen()
