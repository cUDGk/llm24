"""言語判定 & フィルタの単体テスト。"""

from server.scheduler import _detect_lang, _is_allowed_language


def test_japanese_kana():
    assert _detect_lang("YOASOBI アイドル") == "ja"


def test_japanese_kanji_only():
    # 漢字のみ → アプリの主市場が日本なので ja 扱い
    assert _detect_lang("米津玄師 感電") == "ja"


def test_japanese_mixed():
    assert _detect_lang("Mrs. GREEN APPLE ライラック") == "ja"


def test_english_ascii():
    assert _detect_lang("Mac Miller Self Care") == "en"


def test_korean():
    assert _detect_lang("아이유 복숭아") == "ko"


def test_russian():
    assert _detect_lang("Земфира Прости") == "ru"


def test_arabic():
    assert _detect_lang("عمرو دياب تملي معاك") == "ar"


def test_thai():
    assert _detect_lang("Bodyslam ความเชื่อ") == "th"


def test_empty():
    assert _detect_lang("") == "en"


def test_filter_allow_ja_en():
    allowed = ["ja", "en"]
    assert _is_allowed_language({"artist": "YOASOBI", "title": "アイドル"}, allowed) is True
    assert _is_allowed_language({"artist": "BTS", "title": "Dynamite"}, allowed) is True
    assert _is_allowed_language({"artist": "Земфира", "title": "Прости"}, allowed) is False
    assert _is_allowed_language({"artist": "아이유", "title": "복숭아"}, allowed) is False


def test_filter_empty_allows_all():
    assert _is_allowed_language({"artist": "X", "title": "Прости"}, []) is True
    assert _is_allowed_language({"artist": "X", "title": "Прости"}, None) is True
