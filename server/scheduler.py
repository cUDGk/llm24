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
import random
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


async def _build_candidate_pool(settings: dict) -> list[dict]:
    """候補プール構築。並列取得 (キャッシュあり)。
    ソース (空のセクションはスキップ):
      A. settings.genres (ジャンル名) で /search
      B. settings.seed_artists (アーティスト名) で /search
      C. /me/top/tracks (settings.use_user_top=True の時のみ)
    プールはランダムシャッフル。
    """
    genres = settings.get("genres", []) or []
    seeds = settings.get("seed_artists", []) or []
    use_top = bool(settings.get("use_user_top", False))

    async def _safe_genre(g: str) -> list[dict]:
        try:
            return await spotify.search_by_genre(g)
        except spotify.SpotifyError:
            return []

    async def _safe_artist(name: str) -> list[dict]:
        try:
            return await spotify.get_artist_top_tracks(name)
        except spotify.SpotifyError:
            return []

    async def _safe_top(tr: str) -> list[dict]:
        try:
            return await spotify.get_top_tracks(time_range=tr, limit=50)
        except spotify.SpotifyError:
            return []

    tasks = [
        asyncio.gather(*(_safe_genre(g) for g in genres)),
        asyncio.gather(*(_safe_artist(n) for n in seeds)),
    ]
    if use_top:
        tasks.append(asyncio.gather(_safe_top("medium_term"), _safe_top("short_term")))

    results = await asyncio.gather(*tasks)

    pool: list[dict] = []
    seen_ids: set[str] = set()
    for group in results:
        for tracks in group:
            for t in tracks:
                if t["id"] in seen_ids:
                    continue
                seen_ids.add(t["id"])
                pool.append(t)

    random.shuffle(pool)
    return pool


async def _pick_from_charts(settings: dict, active_mail: dict | None) -> dict | None:
    """候補プール (top tracks + 検索) から除外を弾いて1曲ランダム選択。"""
    locked_ids = await db.recent_spotify_ids(hours=24)
    recent_plays = await db.recent_plays(limit=20)
    recent_artists = [r["artist"] for r in recent_plays[:2]]

    exclude = settings.get("exclude", {}) or {}
    ex_artists = {a.lower() for a in exclude.get("artists", [])}
    ex_keywords = [k.lower() for k in exclude.get("keywords", [])]

    candidates = await _build_candidate_pool(settings)
    if not candidates:
        return None

    def ok(t: dict) -> bool:
        if t["id"] in locked_ids:
            return False
        if t["artist"].lower() in ex_artists:
            return False
        # 連続同アーティスト2曲制限: 直近2曲のartistと一致したらNG
        if recent_artists.count(t["artist"]) >= 2:
            return False
        hay = (t["artist"] + " " + t["title"]).lower()
        if any(k in hay for k in ex_keywords if k):
            return False
        return True

    pool = [t for t in candidates if ok(t)]
    if not pool:
        # 緩めて recent_artists 制限のみ無視
        pool = [t for t in candidates if t["id"] not in locked_ids]
    if not pool:
        return None

    # active_mail でリクエスト指定があれば、それに近い曲を優先選択 (緩い文字列マッチ)
    if active_mail and (active_mail.get("request") or active_mail.get("body")):
        query = (active_mail.get("request") or active_mail.get("body")).lower()
        scored = [
            (t, 1 if any(q in (t["artist"] + t["title"]).lower() for q in query.split()) else 0)
            for t in pool
        ]
        scored.sort(key=lambda x: x[1], reverse=True)
        # 上位スコアからランダム選択
        top_score = scored[0][1]
        top = [t for t, s in scored if s == top_score]
        return random.choice(top)

    return random.choice(pool)


async def _resolve_mail_track(mail: dict) -> dict | None:
    """お便りのrequest欄を解釈してトラックメタを返す。
    対応:
      - https://open.spotify.com/track/...   → そのトラック
      - https://open.spotify.com/playlist/.. → そのプレイリストから1曲ランダム
    """
    if not mail or not mail.get("request"):
        return None
    req = mail["request"]

    # 1) playlist URL → プレイリストから1曲ランダム
    playlist_id = spotify.parse_playlist_id(req)
    if playlist_id:
        try:
            tracks = await spotify.get_playlist_tracks(playlist_id, limit=100)
        except spotify.SpotifyError as e:
            print(f"[scheduler] playlist fetch failed: {e}", flush=True)
            return None
        if not tracks:
            return None
        locked = await db.recent_spotify_ids(hours=24)
        avail = [t for t in tracks if t["id"] not in locked]
        return random.choice(avail or tracks)

    # 2) track URL → oEmbed + search でメタ解決
    track_id = spotify.parse_track_id(req)
    if not track_id:
        return None

    artist = "(リクエスト)"
    title = "(リクエスト曲)"
    album_image = None
    duration_ms = 0

    meta = await spotify.get_track_oembed(track_id)
    if meta:
        title = (meta.get("title") or "").strip() or title
        album_image = meta.get("thumbnail_url") or None

    if title and title != "(リクエスト曲)":
        try:
            results = await spotify.search_by_track_query(title, limit=10)
            for r in results:
                if r["id"] == track_id:
                    artist = r["artist"] or artist
                    duration_ms = r.get("duration_ms") or 0
                    album_image = album_image or r.get("album_image")
                    break
        except spotify.SpotifyError:
            pass

    return {
        "id": track_id,
        "uri": f"spotify:track:{track_id}",
        "artist": artist,
        "title": title,
        "duration_ms": duration_ms,
        "popularity": None,
        "album_image": album_image,
    }


async def _build_song_segment(
    settings: dict,
    now: datetime,
    active_mail: dict | None = None,
    mail_intro_text: str | None = None,
) -> dict[str, Any]:
    """通常の曲振り or お便り絡みの曲振り。"""
    p = persona.current_persona(now)
    speaker = _voice_id(settings, p.slot, p.default_speaker_id)

    summaries = [s["summary"] for s in await db.recent_summaries(limit=30) if s["summary"]]

    # お便りのリクエストURLが解釈できれば最優先
    track = await _resolve_mail_track(active_mail) if active_mail else None
    if track is None:
        track = await _pick_from_charts(settings, active_mail)
    if not track:
        raise RuntimeError("選曲失敗 (Spotify認証 / シードアーティスト設定を確認)")

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

    # お便り部分は曲の前に逐次再生 (jingle → mail本文 → 曲振り は曲と同時)
    steps: list[dict[str, Any]] = []
    if mail_intro_text:
        if settings.get("jingle_enabled", True):
            steps.append({"type": "jingle", "url": "/assets/jingle_mail.wav"})
        mail_tts = await voicevox.synthesize(mail_intro_text, speaker)
        steps.append({"type": "tts", "url": _cache_url(mail_tts), "text": mail_intro_text})

    # 曲振り TTS は song step に内包 → 曲開始と同時にダッキング再生
    steps.append({
        "type": "song",
        "spotify_uri": track["uri"],
        "spotify_id": track["id"],
        "duration_ms": track["duration_ms"],
        "artist": track["artist"],
        "title": track["title"],
        "album_image": track["album_image"],
        "intro_tts": {"url": _cache_url(intro_tts), "text": intro_text},
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


FALLBACK_LINES = [
    "ちょっと回線が詰まっちゃったみたいで、すみません。次の曲、用意できたらまた呼びますね。",
    "今ちょっと裏でばたついてます。少しだけ待っててください。",
    "ええっと、機材の調子が一瞬。すぐ戻ります。",
]


async def _build_fallback_segment(settings: dict, now: datetime, reason: str) -> dict[str, Any]:
    """Claude/Spotify が失敗した時の保険セグメント。沈黙を避けるため短いTTSだけ流す。"""
    print(f"[scheduler] fallback segment: {reason}", flush=True)
    p = persona.current_persona(now)
    speaker = _voice_id(settings, p.slot, p.default_speaker_id)
    text = random.choice(FALLBACK_LINES)
    try:
        tts_path = await voicevox.synthesize(text, speaker)
        return {
            "kind": "fallback",
            "persona": p.slot,
            "steps": [{"type": "tts", "url": _cache_url(tts_path), "text": text}],
            "next_song": None,
        }
    except Exception as e:
        # VOICEVOX も死んでたらせめて空 segment を返す (フロントが即next-segmentする)
        print(f"[scheduler] fallback TTS also failed: {e}", flush=True)
        return {
            "kind": "fallback",
            "persona": p.slot,
            "steps": [],
            "next_song": None,
        }


# ---- public ----

async def next_segment() -> dict[str, Any]:
    async with _lock:
        if not _state.started:
            raise RuntimeError("scheduler not started (ON AIR押下が必要)")
        now = datetime.now()
        settings = load_settings()

        try:
            return await _next_segment_inner(settings, now)
        except RuntimeError:
            raise
        except Exception as e:
            return await _build_fallback_segment(settings, now, repr(e))


async def _next_segment_inner(settings: dict, now: datetime) -> dict[str, Any]:
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
        return await _build_chat_segment(settings, now)

    # 4. 通常の曲振り
    return await _build_song_segment(settings, now)
