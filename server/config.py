"""環境変数 / 定数。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")


SPOTIFY_CLIENT_ID = os.environ.get("SPOTIFY_CLIENT_ID", "")
SPOTIFY_CLIENT_SECRET = os.environ.get("SPOTIFY_CLIENT_SECRET", "")
SPOTIFY_REDIRECT_URI = os.environ.get(
    "SPOTIFY_REDIRECT_URI", "http://127.0.0.1:8000/auth/spotify/callback"
)

VOICEVOX_BASE_URL = os.environ.get("VOICEVOX_BASE_URL", "http://localhost:50021")

ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")

FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")

LLM24_HOST = os.environ.get("LLM24_HOST", "127.0.0.1")
LLM24_PORT = int(os.environ.get("LLM24_PORT", "8000"))

DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache"
ASSETS_DIR = ROOT / "assets"
WEB_DIR = ROOT / "web"
SETTINGS_PATH = DATA_DIR / "settings.json"
DB_PATH = DATA_DIR / "llm24.db"

DATA_DIR.mkdir(parents=True, exist_ok=True)
CACHE_DIR.mkdir(parents=True, exist_ok=True)
