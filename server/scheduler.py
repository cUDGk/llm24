"""番組進行スケジューラ。

クライアントが /api/next-segment を要求するたびに、次のセグメントを返す。

セグメント種別:
- time_signal: 毎時 00/30 分の時報 (ジングル + 「○時(半)です」TTS)
- mail:        お便り読み上げ (ジングル + 本文 + DJ反応 TTS) + リクエスト曲
- chat:        雑談 (TTS のみ、次曲は無し → 続けてnext-segment要求でsongが来る)
- song:        通常の曲振り (TTS + 曲)

衝突回避:
- 時報は「現在の時刻が直近の時報枠を過ぎている」かつ「再生中の曲が終了」のタイミングで挿入。
  クライアントが next-segment を要求するとき = 1曲再生終了の直後なので、自然に差し込まれる。
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from . import claude_sdk, db, mail_queue, persona, spotify, voicevox
from .config import ASSETS_DIR
from .settings_store import load_settings


@dataclass
class SchedulerState:
    last_time_signal_floor: datetime | None = None
    last_mail_idx: int = -10
    idx: int = 0
    last_chat_at_idx: int = -10
    last_active_mail: dict | None = None  # force/normal問わず直近に読んだお便り
    started: bool = False


_state = SchedulerState()
_lock = asyncio.Lock()


def state() -> SchedulerState:
    return _state


async def start():
    async with _lock:
        _state.started = True
        await db.init_db()


async def stop():
    async with _lock:
        _state.started = False


def _floor_to_half_hour(now: datetime) -> datetime:
    return now.replace(minute=0 if now.minute < 30 else 30, second=0, microsecond=0)


def _should_play_time_signal(now: datetime) -> bool:
    cur_floor = _floor_to_half_hour(now)
    if _state.last_time_signal_floor is None:
        # 起動直後は次の00/30まで待つ (起動直後にいきなり時報は鳴らさない)
        _state.last_time_signal_floor = cur_floor
        return False
    return cur_floor > _state.last_time_signal_floor


def _hour_label(now: datetime) -> str:
    h = now.hour
    if now.minute < 30:
        return f"{h}時です。LLM24。"
    return f"{h}時半です。LLM24。"


async def _build_time_signal(now: datetime, settings: dict) -> dict[str, Any]:
    _state.last_time_signal_floor = _floor_to_half_hour(now)
    p = persona.current_persona(now)
    speaker = _voice_id(settings, p.slot, p.default_speaker_id)
    text = _hour_label(now)
    tts_path = await voicevox.synthesize(text, speaker)
    return {
        "kind": "time_signal",
        "persona": p.slot,
        "steps": [
            {"type": "jingle", "url": "/assets/jingle_time.wav"} if settings.get("jingle_enabled", True) else None,
            {"type": "tts", "url": _cache_url(tts_path), "text": text},
        ],
        "next_song": None,
    }


def _voice_id(settings: dict, slot: str, default: int) -> int:
    return int(settings.get("voice_assignment", {}).get(slot, default))


def _cache_url(path: Path) -> str:
    return f"/cache/{quote(path.name)}"


async def _build_song_segment(
    settings: dict,
    now: datetime,
    active_mail: dict | None = None,
    mail_intro_text: str | None = None,
) -> dict[str, Any]:
    """通常の曲振り or お便り絡みの曲振り。"""
    p = persona.current_persona(now)
    speaker = _voice_id(settings, p.slot, p.default_speaker_id)

    # 選曲 (最大3回リトライ)
    track = None
    chosen = None
    locked_ids = await db.recent_spotify_ids(hours=24)
    recent = await db.recent_plays(limit=20)
    summaries = [s["summary"] for s in await db.recent_summaries(limit=30) if s["summary"]]

    for attempt in range(3):
        try:
            chosen = await claude_sdk.pick_song(
                persona_desc=p.description,
                genres=settings.get("genres", []),
                excludes=settings.get("exclude", {}),
                recent=recent,
                active_mail=active_mail,
            )
        except Exception as e:
            if attempt == 2:
                raise
            continue
        try:
            track = await spotify.search_track(chosen["artist"], chosen["title"])
        except spotify.SpotifyError:
            track = None
        if track and track["id"] not in locked_ids:
            break
        track = None

    if not track:
        raise RuntimeError("選曲に3回失敗")

    # 曲振り台本生成
    intro = await claude_sdk.gen_song_intro(
        persona_desc=p.description,
        artist=track["artist"],
        title=track["title"],
        related_mail=active_mail,
        recent_summaries=summaries,
    )
    intro_text = intro["text"]
    intro_summary = intro.get("summary", intro_text[:20])

    intro_tts = await voicevox.synthesize(intro_text, speaker)

    # 履歴記録
    await db.add_play(track["id"], track["artist"], track["title"])
    await db.add_script(kind="intro", content=intro_text, summary=intro_summary)
    if active_mail:
        await mail_queue.consume_mail(active_mail["id"])

    _state.idx += 1

    # お便りパート (mail_intro_text 渡された場合は前段に挿入)
    steps: list[dict[str, Any]] = []
    if mail_intro_text:
        mail_jingle = settings.get("jingle_enabled", True)
        if mail_jingle:
            steps.append({"type": "jingle", "url": "/assets/jingle_mail.wav"})
        mail_tts = await voicevox.synthesize(mail_intro_text, speaker)
        steps.append({"type": "tts", "url": _cache_url(mail_tts), "text": mail_intro_text})

    steps.append({"type": "tts", "url": _cache_url(intro_tts), "text": intro_text, "ducking": "intro"})
    steps.append({
        "type": "song",
        "spotify_uri": track["uri"],
        "spotify_id": track["id"],
        "duration_ms": track["duration_ms"],
        "artist": track["artist"],
        "title": track["title"],
        "album_image": track["album_image"],
    })

    return {
        "kind": "song",
        "persona": p.slot,
        "steps": steps,
        "next_song": track,
    }


async def _build_chat_segment(settings: dict, now: datetime) -> dict[str, Any]:
    p = persona.current_persona(now)
    speaker = _voice_id(settings, p.slot, p.default_speaker_id)
    recent = await db.recent_plays(limit=5)
    summaries = [s["summary"] for s in await db.recent_summaries(limit=30) if s["summary"]]
    chat = await claude_sdk.gen_chat(
        persona_desc=p.description,
        last_played=recent,
        recent_summaries=summaries,
    )
    tts_path = await voicevox.synthesize(chat["text"], speaker)
    await db.add_script(kind="chat", content=chat["text"], summary=chat.get("summary"))
    _state.last_chat_at_idx = _state.idx
    return {
        "kind": "chat",
        "persona": p.slot,
        "steps": [
            {"type": "tts", "url": _cache_url(tts_path), "text": chat["text"]},
        ],
        "next_song": None,
    }


async def _build_mail_then_song(settings: dict, now: datetime, mail: dict) -> dict[str, Any]:
    """お便り読み上げ → 続けて (リクエスト反映した) 曲振り → 曲。
    1セグメントにまとめて返す。
    """
    p = persona.current_persona(now)
    summaries = [s["summary"] for s in await db.recent_summaries(limit=30) if s["summary"]]
    reply = await claude_sdk.gen_mail_reply(
        persona_desc=p.description,
        mail=mail,
        recent_summaries=summaries,
    )
    await db.add_script(kind="mail", content=reply["text"], summary=reply.get("summary"))
    await mail_queue.mark_read(mail["id"])
    _state.last_mail_idx = _state.idx
    _state.last_active_mail = mail
    # mail_intro_text を渡して song segment に内包させる
    return await _build_song_segment(settings, now, active_mail=mail, mail_intro_text=reply["text"])


# ---- public ----

async def next_segment() -> dict[str, Any]:
    async with _lock:
        if not _state.started:
            raise RuntimeError("scheduler not started (ON AIR押下が必要)")
        now = datetime.now()
        settings = load_settings()

        # 1. 時報判定
        if _should_play_time_signal(now):
            return await _build_time_signal(now, settings)

        # 2. お便り判定 (force/通常)
        mail = await mail_queue.pick_next_mail(
            settings.get("mail_adoption", "every_few"),
            _state.last_mail_idx,
            _state.idx,
        )
        if mail:
            return await _build_mail_then_song(settings, now, mail)

        # 3. 雑談頻度に応じてたまに雑談を挟む
        freq = settings.get("chat_frequency", "normal")
        gap = {"loose": 6, "normal": 4, "dense": 2}.get(freq, 4)
        if _state.idx - _state.last_chat_at_idx >= gap:
            chat = await _build_chat_segment(settings, now)
            return chat

        # 4. 通常の曲振り
        return await _build_song_segment(settings, now)
