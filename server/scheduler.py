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
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote


_RE_HIRAGANA = re.compile(r"[぀-ゟ]")
_RE_KATAKANA = re.compile(r"[゠-ヿ]")
_RE_CJK = re.compile(r"[一-鿿]")
_RE_HANGUL = re.compile(r"[가-힯ᄀ-ᇿ]")
_RE_CYRILLIC = re.compile(r"[Ѐ-ӿ]")
_RE_ARABIC = re.compile(r"[؀-ۿ]")
_RE_THAI = re.compile(r"[฀-๿]")
_RE_DEVANAGARI = re.compile(r"[ऀ-ॿ]")


def _detect_lang(text: str) -> str:
    """タイトル+アーティスト文字列から大まかな言語を推定。"""
    if not text:
        return "en"
    if _RE_HIRAGANA.search(text) or _RE_KATAKANA.search(text):
        return "ja"  # ひらカナがあれば日本語確定
    if _RE_HANGUL.search(text):
        return "ko"
    if _RE_CYRILLIC.search(text):
        return "ru"
    if _RE_ARABIC.search(text):
        return "ar"
    if _RE_THAI.search(text):
        return "th"
    if _RE_DEVANAGARI.search(text):
        return "hi"
    if _RE_CJK.search(text):
        # 漢字のみ → 日本語か中国語か曖昧。ここではアプリの主市場が日本なので "ja" 扱い
        return "ja"
    return "en"


def _is_allowed_language(track: dict, allowed: list[str]) -> bool:
    if not allowed:
        return True
    text = f"{track.get('artist','')} {track.get('title','')}"
    lang = _detect_lang(text)
    return lang in allowed

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
    current_genre_idx: int = 0          # 現在使ってる genre のインデックス
    songs_in_current_genre: int = 0      # 現在 genre で連続して流した曲数
    songs_since_intro: int = 99          # 直近の曲振りトークから何曲経ったか (初回は必ず喋るよう大きく)


_state = SchedulerState()
_lock = asyncio.Lock()
_prefetched_segment: dict | None = None
_prefetch_task: asyncio.Task | None = None


def state() -> SchedulerState:
    return _state


async def start():
    global _prefetch_task, _prefetched_segment
    async with _lock:
        _state.started = True
        await db.init_db()
    # まず 0.x 秒で出せる opener segment を同期セット (Claude不要、 VOICEVOXのみ)。
    # これでユーザーの 「開始 → 即音」体験が確定する。
    settings = load_settings()
    p = persona.current_persona(datetime.now())
    speaker = _voice_id(settings, p.slot, p.default_speaker_id)
    opener_text = random.choice(OPENER_LINES)
    _prefetched_segment = {
        "kind": "opener",
        "persona": p.slot,
        "steps": [{"type": "tts", "text": opener_text, "speaker": speaker}],
        "next_song": None,
    }
    # 並行で本格 segment を生成 (Claude 等で時間かかる) → opener 消化後にすぐ提供できる
    _prefetch_task = asyncio.create_task(_warm_first_segment_full())


async def stop():
    global _prefetched_segment, _prefetch_task
    async with _lock:
        _state.started = False
    _prefetched_segment = None
    if _prefetch_task and not _prefetch_task.done():
        _prefetch_task.cancel()
    _prefetch_task = None


OPENER_LINES = [
    "LLM24、オンエアです。深呼吸ひとつ、ゆっくり始めましょう。今夜も最後までお付き合いください。",
    "こんばんは、LLM24です。お疲れさまでした、楽にして聴いてください。それでははじめます。",
    "LLM24、はじまります。今夜はあなたの隣で、淡々と曲を回していきますので、よろしくお願いします。",
    "LLM24です。手を動かしながらでも、横になっていてもどうぞ。今夜の最初の一曲、もうすぐかけます。",
]


async def _warm_first_segment_full():
    """opener 消化後にすぐ流せるよう、 通常の next_segment を 1 つ準備しておく。"""
    global _prefetched_segment
    try:
        import time as _time
        settings = load_settings()
        now = datetime.now()
        t0 = _time.monotonic()
        try:
            seg = await _next_segment_inner(settings, now)
        except Exception as e:
            seg = await _build_fallback_segment(settings, now, repr(e))
        dt = _time.monotonic() - t0
        # opener がまだ取られていなければそのまま (ユーザー取りに来ると opener)、
        # opener が消費済みなら本物に置換
        if _prefetched_segment is None or _prefetched_segment.get("kind") == "opener":
            # opener はそのまま、本物は別保存できる枠が無いのでここでは触らない
            # = opener取得時に再度本物の warm をキックする方が良い
            pass
        else:
            pass
        # 一旦どちらかが消化されてからの提供は next_segment 側で待ち合わせるので、
        # ここでは _prefetched_segment が None だった場合のみセット
        if _prefetched_segment is None:
            _prefetched_segment = seg
            print(f"[scheduler] warm-full set as prefetched in {dt:.2f}s kind={seg.get('kind')}", flush=True)
        else:
            # opener が残っている → そのままにしておき、 next_segment が opener を返した直後の
            # 呼び出しで _next_segment_inner が走る代わりに、 ここで作った seg を覚えておく
            _PendingFullSegment.value = seg
            print(f"[scheduler] warm-full queued (opener still pending) in {dt:.2f}s kind={seg.get('kind')}", flush=True)
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[scheduler] warm failed: {e}", flush=True)


class _PendingFullSegment:
    """opener の後に出すべき本格 segment をひとまず置いておくスロット。"""
    value: dict | None = None


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
    steps = []
    if settings.get("jingle_enabled", True):
        steps.append({"type": "jingle", "url": "/assets/jingle_time.wav"})
    steps.append({"type": "tts", "text": text, "speaker": speaker})
    return {"kind": "time_signal", "persona": p.slot, "steps": steps, "next_song": None}


def _voice_id(settings: dict, slot: str, default: int) -> int:
    return int(settings.get("voice_assignment", {}).get(slot, default))


def _cache_url(path: Path) -> str:
    return f"/cache/{quote(path.name)}"


def _active_genre(settings: dict) -> str | None:
    """ローテーションで今使うべきジャンル。設定が空なら None。"""
    genres = settings.get("genres", []) or []
    if not genres:
        return None
    return genres[_state.current_genre_idx % len(genres)]


def _advance_genre_rotation(settings: dict) -> None:
    """song が1曲完了するごとに呼ぶ。run_length を超えたら次ジャンルへ。"""
    run = max(1, int(settings.get("genre_run_length", 4)))
    _state.songs_in_current_genre += 1
    if _state.songs_in_current_genre >= run:
        _state.songs_in_current_genre = 0
        _state.current_genre_idx += 1


async def _build_candidate_pool(settings: dict) -> list[dict]:
    """候補プール構築。並列取得 (キャッシュあり)。
    ソース (空のセクションはスキップ):
      A. ローテーション中の単一ジャンルで /search → 系統に一貫性
      B. settings.seed_artists (アーティスト名) で /search
      C. /me/top/tracks (settings.use_user_top=True の時のみ)
    """
    active_genre = _active_genre(settings)
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

    tasks = []
    if active_genre:
        tasks.append(_safe_genre(active_genre))
    if seeds:
        tasks.append(asyncio.gather(*(_safe_artist(n) for n in seeds)))
    if use_top:
        tasks.append(asyncio.gather(_safe_top("medium_term"), _safe_top("short_term")))

    if not tasks:
        return []
    results = await asyncio.gather(*tasks)

    pool: list[dict] = []
    seen_ids: set[str] = set()
    for r in results:
        groups = r if isinstance(r, list) and r and isinstance(r[0], list) else [r]
        for tracks in groups:
            for t in tracks:
                if t["id"] in seen_ids:
                    continue
                seen_ids.add(t["id"])
                pool.append(t)

    random.shuffle(pool)
    return pool


async def _pick_from_charts(settings: dict, active_mail: dict | None) -> dict | None:
    """候補プール (top tracks + 検索) から除外を弾いて1曲ランダム選択。
    現在ジャンルのプールが空 (or 全部除外で残らない) なら次ジャンルへ自動切替し、
    最大3回まで再試行する。"""
    locked_ids = await db.recent_spotify_ids(hours=24)
    recent_plays = await db.recent_plays(limit=20)
    recent_artists = [r["artist"] for r in recent_plays[:2]]

    exclude = settings.get("exclude", {}) or {}
    ex_artists = {a.lower() for a in exclude.get("artists", [])}
    ex_keywords = [k.lower() for k in exclude.get("keywords", [])]
    allowed_languages = settings.get("allowed_languages") or []
    genres_list = settings.get("genres", []) or []

    def ok(t: dict) -> bool:
        if t["id"] in locked_ids:
            return False
        if t["artist"].lower() in ex_artists:
            return False
        if recent_artists.count(t["artist"]) >= 2:
            return False
        hay = (t["artist"] + " " + t["title"]).lower()
        if any(k in hay for k in ex_keywords if k):
            return False
        if allowed_languages and not _is_allowed_language(t, allowed_languages):
            return False
        return True

    # 最大 (ジャンル数) 回試行: 現在ジャンルで条件合致なし → 次ジャンルへ。
    # 言語フィルタはユーザー意思なので絶対に緩和しない。
    max_attempts = max(1, len(genres_list) or 1)
    candidates: list[dict] = []
    for attempt in range(max_attempts):
        pool = await _build_candidate_pool(settings)
        candidates = [t for t in pool if ok(t)]
        if candidates:
            break
        if len(genres_list) > 1 and attempt < max_attempts - 1:
            _state.current_genre_idx += 1
            _state.songs_in_current_genre = 0
            print(f"[scheduler] pool empty, advancing genre → {_active_genre(settings)}", flush=True)

    if not candidates:
        return None

    return random.choice(candidates)


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

    # 曲振りトークを生成するか判定
    intro_every = max(1, int(settings.get("intro_every", 1)))
    # お便り絡みの曲では必ずトークする (お便りの読み上げと一体)、それ以外は intro_every 周期
    should_speak = bool(active_mail) or _state.songs_since_intro >= intro_every - 1

    intro_text = None
    intro_summary = None
    if should_speak:
        intro = await claude_sdk.gen_song_intro(
            persona_desc=p.description,
            artist=track["artist"],
            title=track["title"],
            related_mail=active_mail,
            recent_summaries=summaries,
        )
        intro_text = intro["text"]
        intro_summary = intro.get("summary", intro_text[:20])
        _state.songs_since_intro = 0
    else:
        _state.songs_since_intro += 1

    # 履歴記録
    await db.add_play(track["id"], track["artist"], track["title"])
    if intro_text:
        await db.add_script(kind="intro", content=intro_text, summary=intro_summary)
    if active_mail:
        await mail_queue.consume_mail(active_mail["id"])

    _state.idx += 1
    if not active_mail:
        _advance_genre_rotation(settings)

    # お便り部分は曲の前に逐次再生 (jingle → mail本文 → 曲と同時に intro)
    steps: list[dict[str, Any]] = []
    if mail_intro_text:
        if settings.get("jingle_enabled", True):
            steps.append({"type": "jingle", "url": "/assets/jingle_mail.wav"})
        steps.append({"type": "tts", "text": mail_intro_text, "speaker": speaker})

    song_step: dict[str, Any] = {
        "type": "song",
        "spotify_uri": track["uri"],
        "spotify_id": track["id"],
        "duration_ms": track["duration_ms"],
        "artist": track["artist"],
        "title": track["title"],
        "album_image": track["album_image"],
    }
    if intro_text:
        song_step["intro_tts"] = {"text": intro_text, "speaker": speaker}
    steps.append(song_step)

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
    await db.add_script(kind="chat", content=chat["text"], summary=chat.get("summary"))
    _state.last_chat_at_idx = _state.idx
    return {
        "kind": "chat",
        "persona": p.slot,
        "steps": [{"type": "tts", "text": chat["text"], "speaker": speaker}],
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
    return {
        "kind": "fallback",
        "persona": p.slot,
        "steps": [{"type": "tts", "text": text, "speaker": speaker}],
        "next_song": None,
    }


# ---- public ----

async def next_segment() -> dict[str, Any]:
    global _prefetched_segment, _prefetch_task
    import time as _time

    # まず即時取得可能なものがあれば返す (opener 等)
    if _prefetched_segment is not None:
        async with _lock:
            if not _state.started:
                raise RuntimeError("scheduler not started (ON AIR押下が必要)")
            if _prefetched_segment is not None:
                seg = _prefetched_segment
                _prefetched_segment = None
                # opener を消化した直後なら、 warm-full で用意した本格 seg を次回の prefetched に
                if seg.get("kind") == "opener" and _PendingFullSegment.value is not None:
                    _prefetched_segment = _PendingFullSegment.value
                    _PendingFullSegment.value = None
                print(f"[scheduler] served prefetched kind={seg.get('kind')}", flush=True)
                return seg

    # まだ無い → warm task の完了を待つ
    if _prefetch_task is not None and not _prefetch_task.done():
        try:
            await _prefetch_task
        except (asyncio.CancelledError, Exception):
            pass
    _prefetch_task = None

    async with _lock:
        if not _state.started:
            raise RuntimeError("scheduler not started (ON AIR押下が必要)")
        if _prefetched_segment is not None:
            seg = _prefetched_segment
            _prefetched_segment = None
            if seg.get("kind") == "opener" and _PendingFullSegment.value is not None:
                _prefetched_segment = _PendingFullSegment.value
                _PendingFullSegment.value = None
            print(f"[scheduler] served prefetched (post-wait) kind={seg.get('kind')}", flush=True)
            return seg
        now = datetime.now()
        settings = load_settings()
        t0 = _time.monotonic()
        try:
            seg = await _next_segment_inner(settings, now)
        except RuntimeError as e:
            # 'not started' だけは正常 (offair済み) として 409 にする
            if "not started" in str(e):
                raise
            print(f"[scheduler] runtime error → fallback: {e}", flush=True)
            seg = await _build_fallback_segment(settings, now, repr(e))
        except Exception as e:
            print(f"[scheduler] unhandled → fallback: {e}", flush=True)
            seg = await _build_fallback_segment(settings, now, repr(e))
        dt = _time.monotonic() - t0
        steps_count = len(seg.get("steps") or [])
        print(f"[scheduler] next_segment kind={seg.get('kind')} {dt:.2f}s steps={steps_count}", flush=True)
        return seg


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
