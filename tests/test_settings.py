"""設定ストアのテスト。"""

from server import settings_store


def test_defaults_load():
    s = settings_store.load_settings()
    assert "genres" in s
    assert "seed_artists" in s
    assert isinstance(s["seed_artists"], list)


def test_update_persists():
    settings_store.update_settings({"chat_frequency": "loose"})
    s = settings_store.load_settings()
    assert s["chat_frequency"] == "loose"


def test_partial_update_keeps_defaults():
    settings_store.update_settings({"chat_frequency": "dense"})
    s = settings_store.load_settings()
    assert s["chat_frequency"] == "dense"
    # seed_artists は触ってないので残ってる
    assert "seed_artists" in s
