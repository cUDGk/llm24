"""FastAPI エントリポイント。

エンドポイント:
- GET  /                       → index.html
- GET  /static/*               → CSS/JS
- GET  /assets/*               → ジングル素材
- GET  /cache/<file>           → 生成済みTTS WAV
- GET  /auth/spotify           → Spotify認可URLへリダイレクト
- GET  /auth/spotify/callback  → 認可コード受領→トークン保存→ /へ
- GET  /api/status             → サーバ状態
- GET  /api/spotify/token      → 現在の access_token (Web Playback SDK用)
- POST /api/onair              → 番組開始
- POST /api/offair             → 番組停止
- GET  /api/next-segment       → 次のセグメント取得
- POST /api/mail               → お便り投稿
- GET  /api/mail               → お便り一覧
- GET  /api/settings           → 現在設定
- PUT  /api/settings           → 設定更新
- GET  /api/now                → 今再生中の曲・最近の曲
"""

from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import uvicorn
from fastapi import FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import (
    FileResponse,
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import db, scheduler, settings_store, spotify
from .config import (
    ASSETS_DIR,
    CACHE_DIR,
    LLM24_HOST,
    LLM24_PORT,
    WEB_DIR,
)


_oauth_state_store: set[str] = set()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db.init_db()
    yield


app = FastAPI(title="LLM24", lifespan=lifespan)

app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")
app.mount("/assets", StaticFiles(directory=str(ASSETS_DIR)), name="assets")
app.mount("/cache", StaticFiles(directory=str(CACHE_DIR)), name="cache")


@app.get("/", response_class=HTMLResponse)
async def index():
    idx = WEB_DIR / "index.html"
    return FileResponse(idx)


# ----- Spotify OAuth -----

@app.get("/auth/spotify")
async def auth_spotify():
    state = secrets.token_urlsafe(16)
    _oauth_state_store.add(state)
    return RedirectResponse(spotify.authorize_url(state))


@app.get("/auth/spotify/callback")
async def auth_callback(code: str | None = None, state: str | None = None, error: str | None = None):
    if error:
        return HTMLResponse(f"<h1>Spotify認証エラー</h1><p>{error}</p>", status_code=400)
    if not code or not state or state not in _oauth_state_store:
        return HTMLResponse("<h1>不正な認証コールバック</h1>", status_code=400)
    _oauth_state_store.discard(state)
    try:
        await spotify.exchange_code(code)
    except spotify.SpotifyError as e:
        return HTMLResponse(f"<h1>トークン交換失敗</h1><pre>{e}</pre>", status_code=500)
    return RedirectResponse("/")


@app.get("/api/spotify/token")
async def spotify_token():
    if not spotify.is_authenticated():
        raise HTTPException(401, "Spotify未認証")
    try:
        token = await spotify.get_access_token()
    except spotify.SpotifyError as e:
        raise HTTPException(401, str(e)) from e
    return {"access_token": token}


@app.get("/api/spotify/profile")
async def api_spotify_profile():
    if not spotify.is_authenticated():
        raise HTTPException(401, "Spotify未認証")
    p = await spotify.get_user_profile()
    if not p:
        raise HTTPException(502, "Spotify profile fetch failed")
    return {
        "display_name": p.get("display_name"),
        "product": p.get("product"),
        "is_premium": p.get("product") == "premium",
        "country": p.get("country"),
    }


# ----- 番組制御 -----

@app.get("/api/status")
async def api_status():
    return {
        "on_air": scheduler.state().started,
        "spotify_authenticated": spotify.is_authenticated(),
        "idx": scheduler.state().idx,
    }


@app.post("/api/onair")
async def api_onair():
    if not spotify.is_authenticated():
        raise HTTPException(401, "先にSpotifyログインが必要")
    await scheduler.start()
    return {"ok": True, "on_air": True}


@app.post("/api/offair")
async def api_offair():
    await scheduler.stop()
    return {"ok": True, "on_air": False}


@app.get("/api/next-segment")
async def api_next_segment():
    try:
        seg = await scheduler.next_segment()
    except RuntimeError as e:
        raise HTTPException(409, str(e)) from e
    return seg


# ----- お便り -----

class MailIn(BaseModel):
    radio_name: str = Field(..., min_length=1, max_length=60)
    body: str = Field(..., min_length=1, max_length=2000)
    request: str | None = Field(default=None, max_length=500)
    force: bool = False


@app.post("/api/mail")
async def api_mail_post(mail: MailIn):
    mid = await db.add_mail(
        radio_name=mail.radio_name.strip(),
        body=mail.body.strip(),
        request=(mail.request or "").strip() or None,
        force=mail.force,
    )
    return {"id": mid, "ok": True}


@app.get("/api/mail")
async def api_mail_list(status: str | None = None, limit: int = 50):
    return await db.list_mails(status=status, limit=limit)


# ----- 設定 -----

@app.get("/api/settings")
async def api_settings_get():
    return settings_store.load_settings()


@app.put("/api/settings")
async def api_settings_put(payload: dict[str, Any]):
    updated = settings_store.update_settings(payload)
    await db.cache_invalidate_kind("artist_tracks")
    await db.cache_invalidate_kind("genre_tracks")
    return updated


# ----- TTS on-demand (frontend hybrid JA/EN renderer) -----

from . import voicevox as _voicevox
from .persona import current_persona as _current_persona


class TtsIn(BaseModel):
    text: str
    speaker: int | None = None


@app.post("/api/tts")
async def api_tts(payload: TtsIn):
    """フロントから日本語パートを送って VOICEVOX で WAV化。
    speaker 未指定なら時間帯ペルソナのデフォルトを使う。"""
    text = payload.text.strip()
    if not text:
        raise HTTPException(400, "empty text")
    speaker = payload.speaker
    if speaker is None:
        from datetime import datetime
        p = _current_persona(datetime.now())
        speaker = p.default_speaker_id
    try:
        path = await _voicevox.synthesize(text, int(speaker))
    except _voicevox.VoicevoxError as e:
        raise HTTPException(502, str(e)) from e
    return FileResponse(path, media_type="audio/wav")


# ----- Spotify playback (server-side proxy so errors land in logs) -----

_client_device_id: str | None = None


class DeviceIn(BaseModel):
    device_id: str


class PlayIn(BaseModel):
    uri: str


@app.post("/api/spotify/device")
async def api_set_device(payload: DeviceIn):
    global _client_device_id
    _client_device_id = payload.device_id
    print(f"[spotify] client device registered: {_client_device_id}", flush=True)
    try:
        await spotify.transfer_playback(payload.device_id, play=False)
    except spotify.SpotifyError as e:
        print(f"[spotify] transfer warn: {e}", flush=True)
    return {"ok": True}


@app.post("/api/spotify/play")
async def api_spotify_play(payload: PlayIn):
    import asyncio as _asyncio
    if not _client_device_id:
        raise HTTPException(400, "no client device registered yet")

    # 第1試行: 静かにデバイス転送 (play=False) してから目的URI再生。
    # play=True で transfer すると前の曲のキューが一瞬鳴るので、デフォは play=False。
    try:
        await spotify.transfer_playback(_client_device_id, play=False)
        await _asyncio.sleep(0.25)
        await spotify.play_uri(_client_device_id, payload.uri)
        return {"ok": True}
    except spotify.SpotifyError as e1:
        print(f"[spotify] play try1 (silent transfer) failed: {e1}", flush=True)

    # 第2試行: play=True で強制アクティブ化 → 即pauseで前曲を止める → 目的URIへ
    await _asyncio.sleep(0.6)
    try:
        await spotify.transfer_playback(_client_device_id, play=True)
        await _asyncio.sleep(0.2)
        try:
            await spotify.pause(_client_device_id)
        except spotify.SpotifyError:
            pass
        await _asyncio.sleep(0.15)
        await spotify.play_uri(_client_device_id, payload.uri)
        return {"ok": True}
    except spotify.SpotifyError as e2:
        print(f"[spotify] play final fail: {e2}", flush=True)
        raise HTTPException(502, str(e2)) from e2


# ----- client log forward -----

class ClientLog(BaseModel):
    level: str = "info"
    msg: str = ""


@app.post("/api/clientlog")
async def api_clientlog(log: ClientLog):
    print(f"[client:{log.level}] {log.msg}", flush=True)
    return {"ok": True}


# ----- now playing -----

@app.get("/api/now")
async def api_now():
    plays = await db.recent_plays(limit=10)
    cur = plays[0] if plays else None
    return {
        "current": cur,
        "recent": plays[1:6] if len(plays) > 1 else [],
    }


def main():
    uvicorn.run(
        "server.main:app",
        host=LLM24_HOST,
        port=LLM24_PORT,
        reload=False,
        log_level="info",
    )


if __name__ == "__main__":
    main()
