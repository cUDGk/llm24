"""Spotify track / playlist URL/URI 解析の単体テスト。"""

from server.spotify import parse_track_id, parse_playlist_id


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


def test_playlist_url():
    pid = "37i9dQZF1DXcBWIGoYBM5M"
    assert parse_playlist_id(f"https://open.spotify.com/playlist/{pid}") == pid


def test_playlist_url_with_si():
    pid = "37i9dQZF1DXcBWIGoYBM5M"
    assert parse_playlist_id(f"https://open.spotify.com/playlist/{pid}?si=abc") == pid


def test_playlist_uri():
    pid = "37i9dQZF1DXcBWIGoYBM5M"
    assert parse_playlist_id(f"spotify:playlist:{pid}") == pid


def test_playlist_track_not_mixed():
    pid = "37i9dQZF1DXcBWIGoYBM5M"
    # track parser はプレイリストを track と認識しない
    assert parse_track_id(f"https://open.spotify.com/playlist/{pid}") is None
    # playlist parser はトラックをプレイリストと認識しない
    assert parse_playlist_id(f"https://open.spotify.com/track/{VALID_ID}") is None


def test_playlist_empty():
    assert parse_playlist_id("") is None
    assert parse_playlist_id(None) is None
