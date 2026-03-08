"""
KenBot OS — Podcast Clip Engine
Generates short podcast-style AI voiceover scripts and
packages them into YouTube Shorts / Reels.
Requires ElevenLabs for TTS and ffmpeg for video.
"""
from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

from config.settings import settings
from utils.logger import logger

OUTPUT_DIR = Path("output") / "podcast_clips"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

_CLIP_TOPICS = [
    {
        "topic": "why AI will change programming forever",
        "hook": "everyone's talking about AI replacing devs. nobody's talking about what actually changes.",
        "body_prompt": "3-minute breakdown: what jobs survive, what skills matter now, what the shift actually looks like for Indian developers",
    },
    {
        "topic": "the future of gaming in India",
        "hook": "India has 500 million gamers. the esports infrastructure is finally catching up.",
        "body_prompt": "talk about VCT India, IPL esports, streaming scene, why 2026 is the turning point",
    },
    {
        "topic": "how cricket became India's religion",
        "hook": "there's a reason nothing stops for a Kohli innings. cricket isn't entertainment here. it's identity.",
        "body_prompt": "talkback style breakdown of cricket culture, IPL explosion, why T20 changed the game globally",
    },
    {
        "topic": "Bangalore startup culture — reality check",
        "hook": "everyone who moves to Bangalore thinks they're one pitch deck away from a billion dollars.",
        "body_prompt": "honest take on startup culture, survival rate, why the hustle narrative is partly fiction",
    },
]


class PodcastClipEngine:
    """
    Generates AI podcast clip scripts and optionally renders them
    into videos using ElevenLabs TTS + ffmpeg.
    """

    def generate_script(self, topic: Optional[str] = None) -> dict:
        """
        Returns a script dict:
        {topic, hook, script_text, duration_estimate, output_dir}
        """
        if topic:
            # Find matching template or use generic
            match = next((t for t in _CLIP_TOPICS if topic.lower() in t["topic"].lower()), None)
            template = match or {
                "topic": topic,
                "hook": f"here's the real story behind {topic} — nobody talks about this",
                "body_prompt": f"3-minute breakdown on {topic} from Kenneth's perspective",
            }
        else:
            template = random.choice(_CLIP_TOPICS)

        script = self._draft_script(template)
        return {
            "topic":             template["topic"],
            "hook":              template["hook"],
            "script_text":       script,
            "duration_estimate": "60-90 seconds",
            "output_dir":        str(OUTPUT_DIR / template["topic"][:30].replace(" ", "_")),
        }

    def generate_clip(self, topic: Optional[str] = None) -> dict:
        """
        Full pipeline: script → TTS → video.
        Returns {topic, script, video_path, audio_path}.
        Falls back gracefully if TTS/ffmpeg not available.
        """
        script_data = self.generate_script(topic)
        result = dict(script_data)
        result["video_path"] = None
        result["audio_path"] = None

        if not settings.elevenlabs_api_key:
            logger.info("ElevenLabs not configured — returning script only")
            return result

        try:
            audio_path = self._tts(script_data["hook"] + " " + script_data["script_text"])
            result["audio_path"] = str(audio_path)
            # TODO: wrap into video with ffmpeg when video background is available
        except Exception as e:
            logger.error(f"Podcast clip TTS failed: {e}")

        return result

    # ── Internal ──────────────────────────────────────────────────────────

    def _draft_script(self, template: dict) -> str:
        return (
            f"{template['hook']}\n\n"
            f"[INTRO: 5 sec hook]\n\n"
            f"[BODY: {template.get('body_prompt', 'expand naturally')}]\n\n"
            f"[OUTRO: 'drop a follow if u want more of this' — casual, not salesy]\n\n"
            f"Keep it under 90 seconds. Short sentences. Ken's voice — real, not scripted."
        )

    def _tts(self, text: str) -> Path:
        import requests
        headers = {
            "xi-api-key": settings.elevenlabs_api_key,
            "Content-Type": "application/json",
        }
        payload = {
            "text": text[:5000],
            "model_id": "eleven_multilingual_v2",
            "voice_settings": {"stability": 0.5, "similarity_boost": 0.75},
        }
        # Default ElevenLabs voice (Rachel) as fallback
        voice_id = "21m00Tcm4TlvDq8ikWAM"
        r = requests.post(
            f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}",
            headers=headers, json=payload, timeout=30,
        )
        r.raise_for_status()
        import time
        audio_path = OUTPUT_DIR / f"clip_{int(time.time())}.mp3"
        audio_path.write_bytes(r.content)
        return audio_path


podcast_clip_engine = PodcastClipEngine()
