"""時間帯別ペルソナ判定。"""

from datetime import datetime

from server.persona import current_persona, find_persona


def test_midnight():
    p = current_persona(datetime(2026, 5, 12, 2, 0))
    assert p.slot == "midnight"


def test_morning():
    p = current_persona(datetime(2026, 5, 12, 8, 0))
    assert p.slot == "morning"


def test_noon():
    p = current_persona(datetime(2026, 5, 12, 13, 0))
    assert p.slot == "noon"


def test_evening():
    p = current_persona(datetime(2026, 5, 12, 20, 0))
    assert p.slot == "evening"


def test_boundary_midnight_start():
    assert current_persona(datetime(2026, 5, 12, 0, 0)).slot == "midnight"


def test_boundary_morning_start():
    assert current_persona(datetime(2026, 5, 12, 5, 0)).slot == "morning"


def test_find_unknown():
    import pytest
    with pytest.raises(KeyError):
        find_persona("xxx")
