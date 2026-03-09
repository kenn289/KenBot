"""
Ken ClawdBot — YouTube Shorts Generator
Generates punchy viral Shorts: AI slides → styled PNG frames → ffmpeg video → music layer.
No gameplay needed — just vibes, hot takes, and shitpost energy.
"""
from __future__ import annotations

import json
import os
import random
import subprocess
import textwrap
from pathlib import Path
from typing import Optional, List

from config.settings import settings
from core.ai_engine import ken_ai
from utils.logger import logger

MEDIA_DIR = settings.root_dir / "media"
MUSIC_DIR = MEDIA_DIR / "music"
MEDIA_DIR.mkdir(parents=True, exist_ok=True)
MUSIC_DIR.mkdir(parents=True, exist_ok=True)

# Short dimensions (vertical 9:16)
W, H = 1080, 1920

# Vibe → color palette (bg, accent, text)
VIBE_PALETTES = {
    "hype":     {"bg": (5, 5, 15),    "accent": (255, 50, 50),   "text": (255, 255, 255)},
    "dark":     {"bg": (8, 8, 8),     "accent": (180, 0, 255),   "text": (230, 230, 230)},
    "funny":    {"bg": (15, 10, 5),   "accent": (255, 200, 0),   "text": (255, 255, 255)},
    "unhinged": {"bg": (5, 0, 20),    "accent": (0, 255, 160),   "text": (255, 255, 255)},
    "facts":    {"bg": (5, 10, 20),   "accent": (0, 150, 255),   "text": (255, 255, 255)},
}

FONT_IMPACT = "C:/Windows/Fonts/impact.ttf"
FONT_ARIAL_BOLD = "C:/Windows/Fonts/arialbd.ttf"
FONT_ARIAL = "C:/Windows/Fonts/arial.ttf"


class YouTubeContentGen:

    def generate_video_package(
        self,
        topic: Optional[str] = None,
        duration_minutes: int = 5,
    ) -> dict:
        """
        Full pipeline: pick topic → AI slides + metadata → Short video with music.
        Returns package dict with all assets.
        """
        if not topic:
            picked = ken_ai.pick_content_topic()
            topic = f"{picked.get('topic')}: {picked.get('angle')}"

        logger.info(f"📹 Generating YouTube Short for: {topic}")

        # 1. Metadata
        metadata = ken_ai.generate_yt_title_and_description(topic)
        title = metadata.get("title", topic)
        description = metadata.get("description", "")
        tags = metadata.get("tags", [])

        # 2. Short slide content (punchy viral text)
        slides_data = ken_ai.generate_yt_short_slides(topic)
        logger.info(f"🎬 Slides vibe: {slides_data.get('vibe')} | hook: {slides_data.get('hook')}")

        # 3. Script (full text version, saved for reference)
        script = ken_ai.generate_yt_script(topic, duration_minutes=1)

        # 4. Save to dir
        safe_title = "".join(c if c.isalnum() or c in " _-" else "_" for c in title)[:50]
        out_dir = MEDIA_DIR / "youtube" / safe_title.replace(" ", "_")
        out_dir.mkdir(parents=True, exist_ok=True)

        script_path = out_dir / "script.txt"
        meta_path = out_dir / "metadata.json"
        slides_path = out_dir / "slides.json"

        script_path.write_text(script, encoding="utf-8")
        meta_path.write_text(
            json.dumps({"title": title, "description": description, "tags": tags}, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        slides_path.write_text(json.dumps(slides_data, indent=2, ensure_ascii=False), encoding="utf-8")

        # 5. Build Short video
        video_path = self._create_short_video(out_dir, slides_data, title)

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

    # ------------------------------------------------------------------ #
    #  Short video builder                                                  #
    # ------------------------------------------------------------------ #

    def _create_short_video(self, out_dir: Path, slides_data: dict, title: str) -> Optional[Path]:
        """
        Build a proper YouTube Short:
          PNG slides (Pillow, styled by vibe) → ffmpeg per-clip fades → concat → music layer
        """
        try:
            from PIL import Image, ImageDraw, ImageFont

            vibe = slides_data.get("vibe", "unhinged")
            palette = VIBE_PALETTES.get(vibe, VIBE_PALETTES["unhinged"])
            bg_color = palette["bg"]
            accent = palette["accent"]
            text_color = palette["text"]

            # Build full slide list: hook → slides → cta
            all_slides: List[str] = []
            if slides_data.get("hook"):
                all_slides.append(slides_data["hook"])
            all_slides.extend(slides_data.get("slides", []))
            if slides_data.get("cta"):
                all_slides.append(slides_data["cta"])

            # Duration per slide (seconds): hook = 2.5s, normal = 3s, cta = 2s
            durations = []
            for i, slide in enumerate(all_slides):
                if i == 0:
                    durations.append(2.5)
                elif i == len(all_slides) - 1:
                    durations.append(2.0)
                else:
                    durations.append(3.0)

            # Load fonts
            try:
                font_big = ImageFont.truetype(FONT_IMPACT, 110)
                font_med = ImageFont.truetype(FONT_IMPACT, 70)
                font_small = ImageFont.truetype(FONT_ARIAL_BOLD, 42)
                font_watermark = ImageFont.truetype(FONT_ARIAL, 32)
            except OSError:
                font_big = font_med = font_small = font_watermark = ImageFont.load_default()

            clip_paths = []

            for idx, (slide_text, dur) in enumerate(zip(all_slides, durations)):
                img_path = out_dir / f"slide_{idx:02d}.png"
                clip_path = out_dir / f"clip_{idx:02d}.mp4"

                # --- Draw slide ---
                img = Image.new("RGB", (W, H), color=bg_color)
                draw = ImageDraw.Draw(img)

                # Accent gradient bar (left side)
                for px in range(12):
                    alpha = int(255 * (1 - px / 12))
                    draw.rectangle([px, 0, px, H], fill=accent)

                # Bottom accent bar
                draw.rectangle([0, H - 8, W, H], fill=accent)

                # Slide number dots (top right)
                dot_x = W - 40
                for d in range(len(all_slides)):
                    color = accent if d == idx else (60, 60, 60)
                    draw.ellipse([dot_x - 8, 50, dot_x + 8, 66], fill=color)
                    dot_x -= 26

                # Choose font size based on text length
                clean_text = self._strip_emoji(slide_text)
                is_cta = idx == len(all_slides) - 1
                is_hook = idx == 0

                if len(clean_text) > 40:
                    font = font_med
                    line_h = 85
                    max_w = 22
                elif len(clean_text) > 20:
                    font = font_big
                    line_h = 125
                    max_w = 14
                else:
                    font = font_big
                    line_h = 125
                    max_w = 14

                if is_cta:
                    font = font_small
                    line_h = 55
                    max_w = 28

                # Word wrap
                wrapped = textwrap.wrap(clean_text, width=max_w)
                total_h = len(wrapped) * line_h
                y = (H - total_h) // 2

                for line in wrapped:
                    bbox = draw.textbbox((0, 0), line, font=font)
                    tw = bbox[2] - bbox[0]
                    x = (W - tw) // 2

                    # Black stroke (shadow)
                    for ox, oy in [(-4, -4), (4, -4), (-4, 4), (4, 4), (0, 5)]:
                        draw.text((x + ox, y + oy), line, font=font, fill=(0, 0, 0))

                    # Accent color for hook, white for rest
                    color = accent if is_hook else text_color
                    draw.text((x, y), line, font=font, fill=color)
                    y += line_h

                # Watermark
                draw.text((30, H - 55), "@ken289", font=font_watermark, fill=(120, 120, 140))

                img.save(str(img_path))

                # --- ffmpeg: PNG → video clip with fade in/out ---
                fps = 30
                total_frames = int(dur * fps)
                fade_frames = min(8, total_frames // 5)

                result = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-loop", "1",
                        "-i", str(img_path),
                        "-t", str(dur),
                        "-vf", f"scale={W}:{H},fade=in:0:{fade_frames},fade=out:{total_frames - fade_frames}:{fade_frames}",
                        "-r", str(fps),
                        "-c:v", "libx264",
                        "-preset", "fast",
                        "-pix_fmt", "yuv420p",
                        str(clip_path),
                    ],
                    capture_output=True,
                    timeout=60,
                )
                if result.returncode != 0:
                    logger.warning(f"Clip {idx} ffmpeg failed: {result.stderr.decode()[:200]}")
                    return None

                clip_paths.append(clip_path)

            # --- Concat all clips ---
            concat_path = out_dir / "short_raw.mp4"
            list_file = out_dir / "concat_list.txt"
            list_file.write_text(
                "\n".join(f"file '{p.name}'" for p in clip_paths),
                encoding="utf-8"
            )

            result = subprocess.run(
                [
                    "ffmpeg", "-y",
                    "-f", "concat",
                    "-safe", "0",
                    "-i", str(list_file),
                    "-vf", f"scale={W}:{H}",
                    "-r", "30",
                    "-c:v", "libx264",
                    "-preset", "fast",
                    "-crf", "23",
                    "-pix_fmt", "yuv420p",
                    "-movflags", "+faststart",
                    str(concat_path),
                ],
                capture_output=True,
                cwd=str(out_dir),
                timeout=180,
            )
            if result.returncode != 0:
                logger.warning(f"Concat failed: {result.stderr.decode()[:300]}")
                return None

            # --- Add music if available ---
            final_path = out_dir / "short_final.mp4"
            music_track = self._pick_music()

            if music_track:
                result = subprocess.run(
                    [
                        "ffmpeg", "-y",
                        "-i", str(concat_path),
                        "-i", str(music_track),
                        "-filter_complex",
                        "[1:a]volume=0.25,afade=t=out:st=0:d=2[music];[music]atrim=0:60[trimmed]",
                        "-map", "0:v",
                        "-map", "[trimmed]",
                        "-shortest",
                        "-c:v", "copy",
                        "-c:a", "aac",
                        "-b:a", "128k",
                        str(final_path),
                    ],
                    capture_output=True,
                    timeout=120,
                )
                if result.returncode == 0:
                    logger.info(f"🎵 Music added: {music_track.name}")
                    return final_path
                else:
                    logger.warning(f"Music mix failed, using silent: {result.stderr.decode()[:150]}")
                    if final_path.exists():
                        final_path.unlink()
                    concat_path.rename(final_path)
                    return final_path
            else:
                if final_path.exists():
                    final_path.unlink()
                concat_path.rename(final_path)
                logger.info("No music tracks in media/music/ — short is silent. Add .mp3/.wav files there.")
                return final_path

        except Exception as exc:
            logger.warning(f"Short video creation failed ({exc}). Script-only mode.")
            return None

    def _strip_emoji(self, text: str) -> str:
        """Remove emoji characters that Impact font can't render."""
        import re
        return re.sub(
            r'[\U00010000-\U0010ffff'
            r'\U0001F600-\U0001F64F'
            r'\U0001F300-\U0001F5FF'
            r'\U0001F680-\U0001F6FF'
            r'\U0001F1E0-\U0001F1FF'
            r'\u2600-\u26FF\u2700-\u27BF]',
            '', text
        ).strip()

    def _pick_music(self) -> Optional[Path]:
        """Pick a random music track from media/music/ — supports .mp3, .m4a, .wav."""
        tracks = (
            list(MUSIC_DIR.glob("*.mp3"))
            + list(MUSIC_DIR.glob("*.m4a"))
            + list(MUSIC_DIR.glob("*.wav"))
        )
        if tracks:
            return random.choice(tracks)
        return None


# Singleton
yt_content = YouTubeContentGen()
