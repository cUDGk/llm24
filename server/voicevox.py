"""VOICEVOX エンジンクライアント。

audio_query → synthesis の2段で WAV を取得する。
キャッシュ: 同じ (text, speaker_id) には同じ WAV を返す。
"""

from __future__ import annotations

import hashlib
from pathlib import Path

import httpx

from .config import CACHE_DIR, VOICEVOX_BASE_URL


class VoicevoxError(RuntimeError):
    pass


# 1.0 がVOICEVOXデフォルト。 大きすぎるとクリップするので 1.5 が上限目安。
VOLUME_SCALE = 1.5


def _cache_key(text: str, speaker_id: int) -> Path:
    h = hashlib.sha256(f"v{VOLUME_SCALE}:{speaker_id}:{text}".encode("utf-8")).hexdigest()[:24]
    return CACHE_DIR / f"tts_{speaker_id}_{h}.wav"


async def synthesize(text: str, speaker_id: int, *, use_cache: bool = True) -> Path:
    """TTSしてWAVファイルパスを返す (音量は VOLUME_SCALE 倍)。"""
    import time as _time
    t0 = _time.monotonic()
    if not text.strip():
        raise VoicevoxError("空のテキストはTTSできない")

    path = _cache_key(text, speaker_id)
    if use_cache and path.exists() and path.stat().st_size > 0:
        print(f"[voicevox] cache hit ({len(text)}ch, spk={speaker_id})", flush=True)
        return path

    async with httpx.AsyncClient(base_url=VOICEVOX_BASE_URL, timeout=60.0) as client:
        q = await client.post(
            "/audio_query",
            params={"text": text, "speaker": speaker_id},
        )
        if q.status_code != 200:
            raise VoicevoxError(f"audio_query failed: {q.status_code} {q.text}")
        query = q.json()
        # 音量を上げる (DJの声が小さいので)
        query["volumeScale"] = VOLUME_SCALE

        s = await client.post(
            "/synthesis",
            params={"speaker": speaker_id},
            json=query,
            headers={"Accept": "audio/wav"},
        )
        if s.status_code != 200:
            raise VoicevoxError(f"synthesis failed: {s.status_code} {s.text}")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(s.content)
    dt = _time.monotonic() - t0
    print(f"[voicevox] gen {dt:.2f}s ({len(text)}ch, spk={speaker_id}, {len(s.content)//1024}KB)", flush=True)
    return path


async def list_speakers() -> list[dict]:
    async with httpx.AsyncClient(base_url=VOICEVOX_BASE_URL, timeout=10.0) as client:
        r = await client.get("/speakers")
        r.raise_for_status()
        return r.json()


async def health_check() -> bool:
    try:
        async with httpx.AsyncClient(base_url=VOICEVOX_BASE_URL, timeout=3.0) as client:
            r = await client.get("/version")
            return r.status_code == 200
    except httpx.HTTPError:
        return False
