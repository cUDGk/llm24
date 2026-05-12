"""Spotify Web API クライアント。

責務:
- OAuth Authorization Code フロー (Client Secret 利用、ローカル限定)
- アクセストークン保存・自動リフレッシュ
- /search でアーティスト+曲名から Track ID 解決
"""

from __future__ import annotations

import base64
import json
import time
import urllib.parse
from pathlib import Path

import httpx

from .config import (
    DATA_DIR,
    SPOTIFY_CLIENT_ID,
    SPOTIFY_CLIENT_SECRET,
    SPOTIFY_REDIRECT_URI,
)


TOKEN_PATH = DATA_DIR / ".spotify_token.json"

SCOPES = [
    "streaming",
    "user-read-email",
    "user-read-private",
    "user-modify-playback-state",
    "user-read-playback-state",
    "user-read-currently-playing",
    "user-top-read",
]


class SpotifyError(RuntimeError):
    pass


def authorize_url(state: str) -> str:
    if not SPOTIFY_CLIENT_ID:
        raise SpotifyError("SPOTIFY_CLIENT_ID が未設定 (.env を確認)")
    params = {
        "client_id": SPOTIFY_CLIENT_ID,
        "response_type": "code",
        "redirect_uri": SPOTIFY_REDIRECT_URI,
        "scope": " ".join(SCOPES),
        "state": state,
        "show_dialog": "false",
    }
    return "https://accounts.spotify.com/authorize?" + urllib.parse.urlencode(params)


def _basic_auth_header() -> dict[str, str]:
    creds = f"{SPOTIFY_CLIENT_ID}:{SPOTIFY_CLIENT_SECRET}".encode("utf-8")
    return {"Authorization": "Basic " + base64.b64encode(creds).decode("ascii")}


def _save_token(payload: dict) -> None:
    payload = dict(payload)
    payload["_obtained_at"] = int(time.time())
    TOKEN_PATH.parent.mkdir(parents=True, exist_ok=True)
    with TOKEN_PATH.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def _load_token() -> dict | None:
    if not TOKEN_PATH.exists():
        return None
    with TOKEN_PATH.open("r", encoding="utf-8") as f:
        return json.load(f)


async def exchange_code(code: str) -> dict:
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            headers=_basic_auth_header(),
            data={
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": SPOTIFY_REDIRECT_URI,
            },
        )
        if r.status_code != 200:
            raise SpotifyError(f"token exchange failed: {r.status_code} {r.text}")
        data = r.json()
        _save_token(data)
        return data


async def refresh_token() -> dict:
    cur = _load_token()
    if not cur or "refresh_token" not in cur:
        raise SpotifyError("refresh_token がない。再ログインが必要。")
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.post(
            "https://accounts.spotify.com/api/token",
            headers=_basic_auth_header(),
            data={
                "grant_type": "refresh_token",
                "refresh_token": cur["refresh_token"],
            },
        )
        if r.status_code != 200:
            raise SpotifyError(f"refresh failed: {r.status_code} {r.text}")
        data = r.json()
        # refresh_token は返ってこない事もある → 既存値を維持
        data.setdefault("refresh_token", cur["refresh_token"])
        _save_token(data)
        return data


async def get_access_token() -> str:
    """有効な access_token を返す。期限切れなら自動リフレッシュ。"""
    cur = _load_token()
    if not cur:
        raise SpotifyError("Spotify未認証。/auth/spotify でログインしてください。")
    obtained = cur.get("_obtained_at", 0)
    expires_in = cur.get("expires_in", 3600)
    # 60秒余裕
    if time.time() > obtained + expires_in - 60:
        cur = await refresh_token()
    return cur["access_token"]


def is_authenticated() -> bool:
    return TOKEN_PATH.exists()


async def search_track(artist: str, title: str) -> dict | None:
    """artist+title で Spotify track 検索。最も人気のヒットを返す。"""
    token = await get_access_token()
    q = f'artist:"{artist}" track:"{title}"'
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://api.spotify.com/v1/search",
            params={"q": q, "type": "track", "limit": 5, "market": "JP"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            raise SpotifyError(f"search failed: {r.status_code} {r.text}")
        items = r.json().get("tracks", {}).get("items", [])
        if not items:
            # 厳密検索失敗 → ゆるい検索でリトライ
            r = await client.get(
                "https://api.spotify.com/v1/search",
                params={"q": f"{artist} {title}", "type": "track", "limit": 5, "market": "JP"},
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                return None
            items = r.json().get("tracks", {}).get("items", [])
        if not items:
            return None
        items.sort(key=lambda t: t.get("popularity", 0), reverse=True)
        top = items[0]
        return {
            "id": top["id"],
            "uri": top["uri"],
            "artist": ", ".join(a["name"] for a in top["artists"]),
            "title": top["name"],
            "duration_ms": top["duration_ms"],
            "popularity": top.get("popularity"),
            "album_image": (top["album"]["images"][0]["url"] if top["album"]["images"] else None),
        }


import re as _re

_TRACK_RE = _re.compile(r"(?:track[:/])([A-Za-z0-9]{22})")


def parse_track_id(url_or_uri: str) -> str | None:
    """Spotify track URL/URI から track id (22文字) を抽出。
    対応: https://open.spotify.com/track/XXX, spotify:track:XXX, intl-* など"""
    if not url_or_uri:
        return None
    m = _TRACK_RE.search(url_or_uri)
    return m.group(1) if m else None


async def get_track_oembed(track_id: str) -> dict | None:
    """Spotifyの oEmbed エンドポイント (認証不要・制限対象外) で track メタを取得。
    /tracks/{id} は新規アプリで403になるので、リクエスト曲のタイトル/サムネはここから。
    返り値例: {"title": "TrackTitle - Artist", "thumbnail_url": "..."}
    """
    url = f"https://open.spotify.com/track/{track_id}"
    try:
        async with httpx.AsyncClient(timeout=8.0, follow_redirects=True) as client:
            r = await client.get(
                "https://open.spotify.com/oembed",
                params={"url": url},
                headers={"User-Agent": "LLM24/1.0"},
            )
            if r.status_code != 200:
                return None
            return r.json()
    except (httpx.HTTPError, ValueError):
        return None


async def search_by_track_query(query: str, limit: int = 5) -> list[dict]:
    """フリーテキストで track 検索 (アーティスト+曲名 のような自然文OK)。"""
    if not query.strip():
        return []
    token = await get_access_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://api.spotify.com/v1/search",
            params={"q": query, "type": "track", "limit": min(limit, 10), "market": "JP"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            raise SpotifyError(f"text search failed: {r.status_code} {r.text}")
        items = r.json().get("tracks", {}).get("items", [])
        return [_normalize_track(t) for t in items if t and t.get("id")]


def _normalize_track(tr: dict) -> dict:
    return {
        "id": tr["id"],
        "uri": tr["uri"],
        "artist": ", ".join(a["name"] for a in tr["artists"]),
        "title": tr["name"],
        "duration_ms": tr["duration_ms"],
        "popularity": tr.get("popularity"),
        "album_image": (tr["album"]["images"][0]["url"] if tr["album"]["images"] else None),
    }


async def get_artist_top_tracks(artist_name: str, market: str = "JP") -> list[dict]:
    """アーティスト名で track 検索 (人気順)。
    Spotify は 2024-11 以降、/artists/{id}/top-tracks を新規アプリで 403 にしたので、
    /search?type=track&q=artist:"NAME" で代替する。
    """
    token = await get_access_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.get(
            "https://api.spotify.com/v1/search",
            params={"q": f'artist:"{artist_name}"', "type": "track", "limit": 10, "market": market},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            raise SpotifyError(f"artist track search failed: {r.status_code} {r.text}")
        items = r.json().get("tracks", {}).get("items", [])
        return [_normalize_track(t) for t in items if t and t.get("id")]


async def get_top_tracks(time_range: str = "medium_term", limit: int = 50) -> list[dict]:
    """ユーザー自身の聴取履歴ベースの top tracks。
    time_range: short_term (4w) / medium_term (6m) / long_term (~all)
    """
    token = await get_access_token()
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://api.spotify.com/v1/me/top/tracks",
            params={"limit": limit, "time_range": time_range},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            raise SpotifyError(f"top tracks failed: {r.status_code} {r.text}")
        return [_normalize_track(t) for t in r.json().get("items", [])]


async def search_recent(year_range: str = "2024-2026", limit: int = 10, query_extra: str = "") -> list[dict]:
    """Search API で年代指定。403対象外 → 公式プレイリスト代替。"""
    token = await get_access_token()
    q = f"year:{year_range}"
    if query_extra:
        q = f"{query_extra} {q}"
    async with httpx.AsyncClient(timeout=15.0) as client:
        r = await client.get(
            "https://api.spotify.com/v1/search",
            params={"q": q, "type": "track", "limit": limit, "market": "JP"},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code != 200:
            raise SpotifyError(f"search failed: {r.status_code} {r.text}")
        items = r.json().get("tracks", {}).get("items", [])
        return [_normalize_track(t) for t in items if t and t.get("id")]


async def get_playlist_tracks(playlist_id: str, limit: int = 100) -> list[dict]:
    """公式プレイリストから曲一覧を取得。"""
    token = await get_access_token()
    out: list[dict] = []
    offset = 0
    async with httpx.AsyncClient(timeout=15.0) as client:
        while len(out) < limit:
            r = await client.get(
                f"https://api.spotify.com/v1/playlists/{playlist_id}/tracks",
                params={
                    "limit": min(50, limit - len(out)),
                    "offset": offset,
                    "market": "JP",
                    "fields": "items(track(id,uri,name,artists(name),album(images),duration_ms,popularity)),next",
                },
                headers={"Authorization": f"Bearer {token}"},
            )
            if r.status_code != 200:
                raise SpotifyError(
                    f"playlist {playlist_id} fetch failed: {r.status_code} {r.text}"
                )
            data = r.json()
            for it in data.get("items", []):
                tr = it.get("track")
                if not tr or not tr.get("id"):
                    continue
                out.append(
                    {
                        "id": tr["id"],
                        "uri": tr["uri"],
                        "artist": ", ".join(a["name"] for a in tr["artists"]),
                        "title": tr["name"],
                        "duration_ms": tr["duration_ms"],
                        "popularity": tr.get("popularity"),
                        "album_image": (
                            tr["album"]["images"][0]["url"]
                            if tr["album"]["images"]
                            else None
                        ),
                    }
                )
            if not data.get("next"):
                break
            offset += 50
    return out


async def transfer_playback(device_id: str, play: bool = False) -> None:
    """Web Playback SDK の device に再生制御権を渡す。"""
    token = await get_access_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.put(
            "https://api.spotify.com/v1/me/player",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"device_ids": [device_id], "play": play},
        )
        if r.status_code not in (200, 202, 204):
            raise SpotifyError(f"transfer_playback failed: {r.status_code} {r.text}")


async def play_uri(device_id: str, uri: str, position_ms: int = 0) -> None:
    token = await get_access_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.put(
            "https://api.spotify.com/v1/me/player/play",
            params={"device_id": device_id},
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"uris": [uri], "position_ms": position_ms},
        )
        if r.status_code not in (200, 202, 204):
            raise SpotifyError(f"play failed: {r.status_code} {r.text}")


async def pause(device_id: str) -> None:
    token = await get_access_token()
    async with httpx.AsyncClient(timeout=10.0) as client:
        r = await client.put(
            "https://api.spotify.com/v1/me/player/pause",
            params={"device_id": device_id},
            headers={"Authorization": f"Bearer {token}"},
        )
        if r.status_code not in (200, 202, 204, 404):
            raise SpotifyError(f"pause failed: {r.status_code} {r.text}")
