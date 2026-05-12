"""Spotify track URL/URI 解析の単体テスト。"""

from server.spotify import parse_track_id


VALID_ID = "78W4mTLIh4qoLu92W4IQhO"


def test_open_url():
    assert parse_track_id(f"https://open.spotify.com/track/{VALID_ID}") == VALID_ID


def test_open_url_with_si():
    assert parse_track_id(f"https://open.spotify.com/track/{VALID_ID}?si=abc123") == VALID_ID


def test_open_url_intl_jp():
    assert parse_track_id(f"https://open.spotify.com/intl-ja/track/{VALID_ID}") == VALID_ID


def test_uri():
    assert parse_track_id(f"spotify:track:{VALID_ID}") == VALID_ID


def test_invalid_url():
    assert parse_track_id("https://example.com/foo") is None


def test_empty():
    assert parse_track_id("") is None
    assert parse_track_id(None) is None


def test_album_url_not_track():
    # album URL は track id を持たない
    assert parse_track_id("https://open.spotify.com/album/abc") is None
