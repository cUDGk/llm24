"""pytest fixtures: テスト用DB / 設定ファイル隔離。

通常テストは tmp_path に隔離。`@pytest.mark.spotify_integration` 付きのテストは
本物の data/ ディレクトリを参照して、サーバ起動時に保存された Spotify token を使う。
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

REAL_DATA = Path(__file__).resolve().parent.parent / "data"


def pytest_configure(config):
    config.addinivalue_line(
        "markers",
        "spotify_integration: real Spotify API (uses saved token; skipped if missing)",
    )


@pytest.fixture(autouse=True)
def isolated_data_dir(request, tmp_path, monkeypatch):
    """各テストごとに data/ を作り直し、DB スキーマも初期化。
    spotify_integration マーカー付きのテストでは隔離せず本物 data/ を参照。"""
    if "spotify_integration" in request.keywords:
        # 本物のディレクトリを使う (.spotify_token.json を読むため)
        from server import config as _c
        from server import db as _db
        from server import settings_store as _s
        from server import spotify as _sp
        monkeypatch.setattr(_c, "DATA_DIR", REAL_DATA)
        monkeypatch.setattr(_c, "CACHE_DIR", REAL_DATA / "cache")
        monkeypatch.setattr(_c, "DB_PATH", REAL_DATA / "llm24.db")
        monkeypatch.setattr(_c, "SETTINGS_PATH", REAL_DATA / "settings.json")
        monkeypatch.setattr(_db, "DB_PATH", REAL_DATA / "llm24.db")
        monkeypatch.setattr(_s, "SETTINGS_PATH", REAL_DATA / "settings.json")
        monkeypatch.setattr(_sp, "TOKEN_PATH", REAL_DATA / ".spotify_token.json")
        yield REAL_DATA
        return

    test_data = tmp_path / "data"
    test_data.mkdir()
    (test_data / "cache").mkdir()

    from server import config as _c
    monkeypatch.setattr(_c, "DATA_DIR", test_data)
    monkeypatch.setattr(_c, "CACHE_DIR", test_data / "cache")
    monkeypatch.setattr(_c, "SETTINGS_PATH", test_data / "settings.json")
    monkeypatch.setattr(_c, "DB_PATH", test_data / "llm24.db")

    from server import db as _db
    monkeypatch.setattr(_db, "DB_PATH", test_data / "llm24.db")
    from server import settings_store as _s
    monkeypatch.setattr(_s, "SETTINGS_PATH", test_data / "settings.json")

    # Spotify TOKEN_PATH もテストディレクトリへ (実 token を触らない)
    from server import spotify as _sp
    monkeypatch.setattr(_sp, "TOKEN_PATH", test_data / ".spotify_token.json")

    asyncio.run(_db.init_db())
    yield test_data
