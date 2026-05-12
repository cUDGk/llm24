"""保存済み Spotify token を使って本物の Spotify Web API を叩く統合テスト。

`data/.spotify_token.json` が無い環境では skip。
ある環境 (= サーバを一度起動して OAuth 済) では実際の API が成功することを確認する。

ブラウザを通さなくてもこれで Spotify 接続を担保できる。
"""

from __future__ import annotations

import pytest

from server import spotify


pytestmark = pytest.mark.spotify_integration


def _token_present():
    return spotify.TOKEN_PATH.exists()


requires_token = pytest.mark.skipif(
    not _token_present(),
    reason="data/.spotify_token.json が存在しない (サーバで一度ログイン必要)",
)


@requires_token
@pytest.mark.asyncio
async def test_get_access_token():
    token = await spotify.get_access_token()
    assert token
    assert len(token) > 20


@requires_token
@pytest.mark.asyncio
async def test_user_profile_has_product():
    p = await spotify.get_user_profile()
    assert p is not None
    assert p.get("product") in ("premium", "free", "open")
    assert "country" in p


@requires_token
@pytest.mark.asyncio
async def test_is_premium_returns_bool():
    result = await spotify.is_premium()
    assert isinstance(result, bool)


@requires_token
@pytest.mark.asyncio
async def test_artist_top_tracks_mrs_green_apple():
    tracks = await spotify.get_artist_top_tracks("Mrs. GREEN APPLE")
    assert len(tracks) > 0
    assert all("id" in t and "uri" in t for t in tracks)
    # 少なくとも1曲は Mrs. GREEN APPLE 名義
    assert any("Mrs. GREEN APPLE" in t["artist"] for t in tracks)


@requires_token
@pytest.mark.asyncio
async def test_search_by_genre_returns_tracks():
    tracks = await spotify.search_by_genre("シティポップ")
    assert len(tracks) > 0
    assert all("id" in t for t in tracks)


@requires_token
@pytest.mark.asyncio
async def test_track_oembed_returns_title():
    meta = await spotify.get_track_oembed("78W4mTLIh4qoLu92W4IQhO")  # Mrs. GREEN APPLE / ライラック
    assert meta is not None
    assert "title" in meta and meta["title"]
    assert "thumbnail_url" in meta


@requires_token
@pytest.mark.asyncio
async def test_search_by_track_query():
    results = await spotify.search_by_track_query("ライラック")
    assert isinstance(results, list)
    # ヒット0は許容 (アカウント国などで結果が変わる) だが構造は壊れていない
    if results:
        assert all("id" in r and "uri" in r for r in results)
