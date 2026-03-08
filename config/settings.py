"""
Ken ClawdBot — Centralized Settings
Loads from .env, validates with pydantic, single source of truth.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import List

from dotenv import load_dotenv
from pydantic import Field
from pydantic_settings import BaseSettings

# Locate repo root and load .env
ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")


class Settings(BaseSettings):
    # ── AI ─────────────────────────────────────────
    anthropic_api_key: str = Field(..., env="ANTHROPIC_API_KEY")
    openai_api_key: str = Field("", env="OPENAI_API_KEY")
    gemini_api_key: str = Field("", env="GEMINI_API_KEY")

    # ── Media ──────────────────────────────────────
    elevenlabs_api_key: str = Field("", env="ELEVENLABS_API_KEY")
    pexels_api_key: str = Field("", env="PEXELS_API_KEY")

    # ── Twitter / X ────────────────────────────────
    twitter_api_key: str = Field("", env="TWITTER_API_KEY")
    twitter_api_secret: str = Field("", env="TWITTER_API_SECRET")
    twitter_access_token: str = Field("", env="TWITTER_ACCESS_TOKEN")
    twitter_access_token_secret: str = Field("", env="TWITTER_ACCESS_TOKEN_SECRET")
    twitter_bearer_token: str = Field("", env="TWITTER_BEARER_TOKEN")
    # Browser automation credentials
    twitter_username: str = Field("", env="TWITTER_USERNAME")
    twitter_password: str = Field("", env="TWITTER_PASSWORD")
    twitter_email: str = Field("", env="TWITTER_EMAIL")      # email for X login verification step
    twitter_phone: str = Field("", env="TWITTER_PHONE")      # phone (e.g. 919XXXXXXXXX) if X asks for phone

    # ── News ──────────────────────────────────────
    news_api_key: str = Field("", env="NEWS_API_KEY")  # optional: newsapi.org free tier
    tavily_api_key: str = Field("", env="TAVILY_API_KEY")  # real-time web search

    # ── Google ─────────────────────────────────────
    google_places_api_key: str = Field("", env="GOOGLE_PLACES_API_KEY")
    google_oauth_credentials: str = Field("./credentials/google_oauth.json", env="GOOGLE_OAUTH_CREDENTIALS")

    # ── Notion ─────────────────────────────────────
    notion_api_key: str = Field("", env="NOTION_API_KEY")
    notion_client_id: str = Field("", env="NOTION_CLIENT_ID")
    notion_client_secret: str = Field("", env="NOTION_CLIENT_SECRET")

    # ── App ────────────────────────────────────────
    flask_port: int = Field(5050, env="FLASK_PORT")
    my_whatsapp_number: str = Field("", env="MY_WHATSAPP_NUMBER")
    ken_real_groups_raw: str = Field("Jaatre bois,Bengaluru Big Ball Beasts👾👾,somalian day care center", env="KEN_REAL_GROUPS")
    log_level: str = Field("INFO", env="LOG_LEVEL")
    timezone: str = Field("Asia/Kolkata", env="TIMEZONE")

    # ── Derived ────────────────────────────────────
    @property
    def ken_real_groups(self) -> List[str]:
        return [g.strip() for g in self.ken_real_groups_raw.split(",") if g.strip()]

    @property
    def root_dir(self) -> Path:
        return ROOT

    @property
    def credentials_dir(self) -> Path:
        return ROOT / "credentials"

    @property
    def media_dir(self) -> Path:
        return ROOT / "media"

    @property
    def memory_dir(self) -> Path:
        return ROOT / "memory" / "sessions"

    class Config:
        env_file = str(ROOT / ".env")
        extra = "ignore"


# Singleton — import this everywhere
settings = Settings()
