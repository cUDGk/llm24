"""ffmpeg ベースの音声連結ユーティリティ。

サーバ側で扱える音声は TTS と Jingle のみ (Spotify 曲は DRM のためクライアント再生)。
ここでは「ジングル + TTS」を1ファイルに連結する関数を提供する。
ダッキング・曲被せはクライアント側 Web Audio API で行う。
"""

from __future__ import annotations

import asyncio
import hashlib
import subprocess
from pathlib import Path

from .config import CACHE_DIR, FFMPEG_BIN


def _key(*parts: str) -> str:
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


async def concat_wavs(inputs: list[Path], out_name: str | None = None) -> Path:
    """複数 wav を順に連結。"""
    if not inputs:
        raise ValueError("inputs is empty")
    if len(inputs) == 1:
        return inputs[0]

    key = out_name or _key(*(str(p) for p in inputs))
    out = CACHE_DIR / f"concat_{key}.wav"
    if out.exists():
        return out

    list_file = CACHE_DIR / f"concat_{key}.txt"
    list_file.write_text(
        "\n".join(f"file '{p.as_posix()}'" for p in inputs),
        encoding="utf-8",
    )

    proc = await asyncio.create_subprocess_exec(
        FFMPEG_BIN,
        "-y", "-loglevel", "error",
        "-f", "concat", "-safe", "0",
        "-i", str(list_file),
        "-c", "copy",
        str(out),
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    _, stderr = await proc.communicate()
    list_file.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg concat failed: {stderr.decode(errors='ignore')}")
    return out
