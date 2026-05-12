"""FastAPI エンドポイントの全網羅テスト。

外部API (Spotify / Claude / VOICEVOX) はモックで切る。
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient

from server import db, main, scheduler, spotify


@pytest.fixture
def client():
    return TestClient(main.app)


def test_index_html(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "LLM24" in r.text


def test_static_css(client):
    r = client.get("/static/style.css")
    assert r.status_code == 200


def test_static_js(client):
    r = client.get("/static/app.js")
    assert r.status_code == 200


def test_status_not_on_air(client):
    with patch.object(spotify, "is_authenticated", return_value=False):
        r = client.get("/api/status")
        assert r.status_code == 200
        body = r.json()
        assert body["on_air"] is False
        assert body["spotify_authenticated"] is False


def test_onair_without_spotify(client):
    with patch.object(spotify, "is_authenticated", return_value=False):
        r = client.post("/api/onair")
        assert r.status_code == 401


def test_settings_get_put(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    s = r.json()
    assert "seed_artists" in s

    r2 = client.put("/api/settings", json={"chat_frequency": "dense"})
    assert r2.status_code == 200
    s2 = r2.json()
    assert s2["chat_frequency"] == "dense"


def test_mail_post_get(client):
    r = client.post("/api/mail", json={
        "radio_name": "Pytest太郎",
        "body": "本文テスト",
        "request": None,
        "force": False,
    })
    assert r.status_code == 200
    assert r.json()["ok"] is True

    r2 = client.get("/api/mail")
    assert r2.status_code == 200
    rows = r2.json()
    assert len(rows) >= 1
    assert rows[0]["radio_name"] == "Pytest太郎"


def test_mail_validation_too_long(client):
    r = client.post("/api/mail", json={
        "radio_name": "x" * 100,  # max=60
        "body": "ok",
    })
    assert r.status_code == 422


def test_mail_validation_empty_name(client):
    r = client.post("/api/mail", json={"radio_name": "", "body": "ok"})
    assert r.status_code == 422


def test_clientlog(client):
    r = client.post("/api/clientlog", json={"level": "error", "msg": "test"})
    assert r.status_code == 200


def test_next_segment_not_on_air(client):
    r = client.get("/api/next-segment")
    assert r.status_code == 409


def test_onair_flow_with_mocked_segment(client, monkeypatch):
    """ON AIR → next-segment → OFF AIR をモックで一周。"""
    # Spotify認証OK扱い
    monkeypatch.setattr(spotify, "is_authenticated", lambda: True)
    # next_segment 内部で呼ばれる外部依存をモック
    async def fake_next():
        return {"kind": "chat", "persona": "evening", "steps": [], "next_song": None}
    monkeypatch.setattr(scheduler, "next_segment", fake_next)

    r1 = client.post("/api/onair")
    assert r1.status_code == 200

    r2 = client.get("/api/next-segment")
    assert r2.status_code == 200
    assert r2.json()["kind"] == "chat"

    r3 = client.post("/api/offair")
    assert r3.status_code == 200


def test_spotify_token_unauthenticated(client):
    with patch.object(spotify, "is_authenticated", return_value=False):
        r = client.get("/api/spotify/token")
        assert r.status_code == 401


def test_spotify_play_no_device(client):
    # device_id 未登録状態 (グローバル変数なのでテスト順依存に注意)
    main._client_device_id = None
    r = client.post("/api/spotify/play", json={"uri": "spotify:track:xxx"})
    assert r.status_code == 400


def test_spotify_device_register(client):
    """device 登録は transfer_playback を裏で呼ぶのでモック。"""
    with patch.object(spotify, "transfer_playback", new=AsyncMock(return_value=None)):
        r = client.post("/api/spotify/device", json={"device_id": "abcdef"})
        assert r.status_code == 200
        assert main._client_device_id == "abcdef"
