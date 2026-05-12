"""pytest fixtures: テスト用DB / 設定ファイル隔離。"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """各テストごとに data/ を作り直し、DB スキーマも初期化。"""
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

    # DBスキーマ初期化 (TestClient の lifespan を待たずに済むように同期実行)
    asyncio.run(_db.init_db())

    yield test_data
