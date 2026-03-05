"""
Ken ClawdBot — YouTube Uploader
Uses YouTube Data API v3 via Google OAuth.
Handles token refresh, upload rate limits, and dedup.

Note: Free YouTube Data API quota = 10,000 units/day.
An upload costs ~1,600 units. Max ~6 uploads/day safely.
"""
from __future__ import annotations

import json
import os
import pickle
from datetime import datetime
from pathlib import Path
from typing import Optional

import httplib2
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload

from config.settings import settings
from memory.store import memory
from utils.helpers import fingerprint
from utils.logger import logger

SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]
TOKEN_PATH = settings.credentials_dir / "youtube_token.pickle"
settings.credentials_dir.mkdir(parents=True, exist_ok=True)

UPLOAD_LIMIT_PER_DAY = 4  # Conservative — YouTube has a daily upload cap


class YouTubeUploader:
    def __init__(self) -> None:
        self._service = None
        self._creds: Optional[Credentials] = None

    def _load_credentials(self) -> Optional[Credentials]:
        """Load or refresh OAuth credentials."""
        creds = None

        # Try cached token
        if TOKEN_PATH.exists():
            with open(TOKEN_PATH, "rb") as f:
                creds = pickle.load(f)

        if creds and creds.valid:
            return creds

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                self._save_credentials(creds)
                return creds
            except Exception as exc:
                logger.error(f"Token refresh failed: {exc}")

        # Need fresh OAuth flow
        oauth_file = Path(settings.google_oauth_credentials)
        if not oauth_file.exists():
            logger.warning(
                f"Google OAuth credentials file not found at {oauth_file}. "
                "YouTube upload disabled. See README for setup instructions."
            )
            return None

        flow = InstalledAppFlow.from_client_secrets_file(str(oauth_file), SCOPES)
        # Use run_console for headless / Windows
        creds = flow.run_local_server(port=0)
        self._save_credentials(creds)
        return creds

    def _save_credentials(self, creds: Credentials) -> None:
        with open(TOKEN_PATH, "wb") as f:
            pickle.dump(creds, f)

    def _get_service(self):
        if self._service:
            return self._service
        creds = self._load_credentials()
        if not creds:
            return None
        self._service = build("youtube", "v3", credentials=creds)
        return self._service

    # ── Budget guard ─────────────────────────────────────
    def _uploads_today(self) -> int:
        key = f"yt_uploads_{datetime.utcnow().date()}"
        return int(memory.get(key, "0"))

    def _increment_upload(self) -> None:
        key = f"yt_uploads_{datetime.utcnow().date()}"
        memory.set(key, str(self._uploads_today() + 1))

    def _can_upload(self) -> bool:
        if self._uploads_today() >= UPLOAD_LIMIT_PER_DAY:
            logger.warning(f"YT daily upload limit ({UPLOAD_LIMIT_PER_DAY}) reached.")
            return False
        return True

    # ── Upload ────────────────────────────────────────────
    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list[str],
        category_id: str = "20",  # 20 = Gaming
        privacy: str = "public",
    ) -> Optional[str]:
        """
        Upload a video to YouTube.
        Returns video ID or None on failure.
        """
        service = self._get_service()
        if not service:
            logger.warning("YouTube service unavailable. Upload skipped.")
            return None

        if not self._can_upload():
            return None

        if not Path(video_path).exists():
            logger.error(f"Video file not found: {video_path}")
            return None

        h = fingerprint(title + video_path)
        if memory.already_posted(h):
            logger.info(f"Video already uploaded (dedup): {title}")
            return None

        body = {
            "snippet": {
                "title": title[:100],
                "description": description,
                "tags": tags[:15],
                "categoryId": category_id,
            },
            "status": {"privacyStatus": privacy},
        }

        media = MediaFileUpload(
            video_path,
            chunksize=10 * 1024 * 1024,  # 10MB chunks
            resumable=True,
            mimetype="video/mp4",
        )

        try:
            logger.info(f"⬆ Uploading to YouTube: {title}")
            request = service.videos().insert(
                part=",".join(body.keys()), body=body, media_body=media
            )

            response = None
            while response is None:
                status, response = request.next_chunk()
                if status:
                    pct = int(status.progress() * 100)
                    logger.info(f"Upload progress: {pct}%")

            video_id = response.get("id")
            memory.mark_posted(h, "youtube", title, video_id)
            self._increment_upload()
            logger.info(f"✅ YouTube upload complete: https://youtu.be/{video_id}")
            return video_id

        except HttpError as exc:
            if "uploadLimitExceeded" in str(exc):
                logger.error("YouTube daily upload cap hit. Retry in 24h.")
            else:
                logger.error(f"YouTube upload error: {exc}")
            return None
        except Exception as exc:
            logger.error(f"YouTube upload unexpected error: {exc}")
            return None

    def upload_package(self, package: dict) -> Optional[str]:
        """Upload a complete video package (from YouTubeContentGen)."""
        if not package.get("video_path"):
            logger.warning("No video file in package. Script-only mode, skipping upload.")
            return None

        return self.upload_video(
            video_path=package["video_path"],
            title=package["title"],
            description=package["description"],
            tags=package.get("tags", []),
        )


# Singleton
yt_uploader = YouTubeUploader()
