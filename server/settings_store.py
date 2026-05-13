"""設定ファイル (data/settings.json) の読み書き。

変更は即座に反映されるが、番組進行は「次の30分枠から」適用する想定で、
scheduler 側がスナップショットを取って使う。
"""

from __future__ import annotations

import json
from threading import RLock
from typing import Any

from .config import SETTINGS_PATH


_lock = RLock()

DEFAULTS: dict[str, Any] = {
    "dj_name": {"common": "LLM24 DJ"},
    "genres": ["J-POP", "シティポップ", "邦楽ロック", "洋楽オルタナ"],
    "exclude": {"artists": [], "genres": [], "keywords": ["クリスマス", "christmas", "xmas"]},
    "personality_custom": "",
    "chat_frequency": "normal",  # loose / normal / dense
    "mail_adoption": "every_few",  # every / every_few / when_full
    "jingle_enabled": True,
    "persona_overrides": {},
    "voice_assignment": {
        "midnight": 13,
        "morning": 11,
        "noon": 11,
        "evening": 53,
    },
    # 推しアーティスト。空ならジャンル設定のみで選曲。
    "seed_artists": [],
    # 自分の Spotify Top Tracks をプールに混ぜるか。
    "use_user_top": False,
    # 1ジャンル何曲連続で流すか。設定 genres を順に消化していく。
    "genre_run_length": 4,
    # 曲振りトーク (intro_tts) を何曲ごとに入れるか。1=毎曲。
    # 3 にすると 3曲流れて1回トーク → ノンストップ感が出る。
    "intro_every": 1,
    # 許可する言語コード。タイトル+アーティスト名の文字種で判定。
    # "ja" (日本語), "en" (英語/ローマ字), "ko" (韓国), "zh" (中国),
    # "ru" (キリル), "ar" (アラビア), "other"
    # デフォは日本語+英語のみ (ロシア/中国/韓国の偏りを避ける)
    "allowed_languages": ["ja", "en"],
}


def load_settings() -> dict[str, Any]:
    with _lock:
        if not SETTINGS_PATH.exists():
            save_settings(DEFAULTS)
            return dict(DEFAULTS)
        with SETTINGS_PATH.open("r", encoding="utf-8") as f:
            data = json.load(f)
        merged = {**DEFAULTS, **data}
        return merged


def save_settings(data: dict[str, Any]) -> None:
    with _lock:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        with SETTINGS_PATH.open("w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


def update_settings(partial: dict[str, Any]) -> dict[str, Any]:
    cur = load_settings()
    cur.update(partial)
    save_settings(cur)
    return cur
