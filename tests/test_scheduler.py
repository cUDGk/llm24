"""scheduler の単体テスト (外部APIモック)。"""

from datetime import datetime
from unittest.mock import AsyncMock, patch

import pytest

from server import db, scheduler, spotify


@pytest.mark.asyncio
async def test_floor_to_half_hour():
    f = scheduler._floor_to_half_hour
    assert f(datetime(2026, 5, 12, 13, 0, 30)) == datetime(2026, 5, 12, 13, 0)
    assert f(datetime(2026, 5, 12, 13, 29, 59)) == datetime(2026, 5, 12, 13, 0)
    assert f(datetime(2026, 5, 12, 13, 30, 0)) == datetime(2026, 5, 12, 13, 30)
    assert f(datetime(2026, 5, 12, 13, 59, 59)) == datetime(2026, 5, 12, 13, 30)


def test_should_play_time_signal_first_call_resets():
    scheduler._state.last_time_signal_floor = None
    now = datetime(2026, 5, 12, 13, 15)
    assert scheduler._should_play_time_signal(now) is False
    # 1回目で last がセットされる
    assert scheduler._state.last_time_signal_floor == datetime(2026, 5, 12, 13, 0)


def test_should_play_time_signal_crosses_half_hour():
    scheduler._state.last_time_signal_floor = datetime(2026, 5, 12, 13, 0)
    # 同じ枠内
    assert scheduler._should_play_time_signal(datetime(2026, 5, 12, 13, 29)) is False
    # 30分過ぎたら True
    assert scheduler._should_play_time_signal(datetime(2026, 5, 12, 13, 30)) is True


@pytest.mark.asyncio
async def test_resolve_mail_track_with_url():
    """oEmbed と search が動くモックで track 解決を確認。"""
    fake_oembed = AsyncMock(return_value={
        "title": "ライラック",
        "thumbnail_url": "https://image/abc",
    })
    fake_search = AsyncMock(return_value=[
        {
            "id": "78W4mTLIh4qoLu92W4IQhO",
            "uri": "spotify:track:78W4mTLIh4qoLu92W4IQhO",
            "artist": "Mrs. GREEN APPLE",
            "title": "ライラック",
            "duration_ms": 288200,
            "popularity": None,
            "album_image": None,
        }
    ])
    with patch.object(spotify, "get_track_oembed", new=fake_oembed), \
         patch.object(spotify, "search_by_track_query", new=fake_search):
        mail = {"request": "https://open.spotify.com/track/78W4mTLIh4qoLu92W4IQhO", "body": "", "radio_name": ""}
        track = await scheduler._resolve_mail_track(mail)

    assert track is not None
    assert track["id"] == "78W4mTLIh4qoLu92W4IQhO"
    assert track["artist"] == "Mrs. GREEN APPLE"
    assert track["title"] == "ライラック"
    assert track["duration_ms"] == 288200


@pytest.mark.asyncio
async def test_resolve_mail_track_no_request():
    assert await scheduler._resolve_mail_track({"request": None}) is None
    assert await scheduler._resolve_mail_track({"request": ""}) is None
    assert await scheduler._resolve_mail_track(None) is None


@pytest.mark.asyncio
async def test_resolve_mail_track_invalid_url():
    assert await scheduler._resolve_mail_track({"request": "https://example.com"}) is None


@pytest.mark.asyncio
async def test_pick_from_charts_returns_track():
    """プールが空でなければ何か返す。"""
    await db.init_db()
    fake_pool = [
        {"id": "id1", "uri": "spotify:track:id1", "artist": "A", "title": "T1",
         "duration_ms": 200000, "popularity": None, "album_image": None},
        {"id": "id2", "uri": "spotify:track:id2", "artist": "B", "title": "T2",
         "duration_ms": 200000, "popularity": None, "album_image": None},
    ]
    with patch.object(scheduler, "_build_candidate_pool", new=AsyncMock(return_value=fake_pool)):
        settings = {"exclude": {"artists": [], "genres": [], "keywords": []}}
        track = await scheduler._pick_from_charts(settings, None)
    assert track is not None
    assert track["id"] in {"id1", "id2"}


@pytest.mark.asyncio
async def test_pick_from_charts_excludes_keyword():
    await db.init_db()
    fake_pool = [
        {"id": "id1", "uri": "u1", "artist": "X", "title": "クリスマス",
         "duration_ms": 1, "popularity": None, "album_image": None},
        {"id": "id2", "uri": "u2", "artist": "Y", "title": "Normal Song",
         "duration_ms": 1, "popularity": None, "album_image": None},
    ]
    with patch.object(scheduler, "_build_candidate_pool", new=AsyncMock(return_value=fake_pool)):
        settings = {"exclude": {"artists": [], "genres": [], "keywords": ["クリスマス"]}}
        track = await scheduler._pick_from_charts(settings, None)
    assert track is not None
    assert track["id"] == "id2"
