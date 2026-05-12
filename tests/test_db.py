"""DB アクセス層の単体テスト。"""

import pytest

from server import db


@pytest.mark.asyncio
async def test_init_and_add_mail():
    await db.init_db()
    mid = await db.add_mail("テストネーム", "本文", "https://x", False)
    assert mid > 0
    rows = await db.list_mails(limit=10)
    assert len(rows) == 1
    assert rows[0]["radio_name"] == "テストネーム"


@pytest.mark.asyncio
async def test_pop_force_mail():
    await db.init_db()
    await db.add_mail("a", "通常", None, False)
    fid = await db.add_mail("b", "force", "リク", True)
    m = await db.pop_force_mail()
    assert m is not None and m["id"] == fid
    n = await db.pop_normal_mail()
    assert n is not None and n["radio_name"] == "a"


@pytest.mark.asyncio
async def test_play_history():
    await db.init_db()
    await db.add_play("id1", "Artist", "Title")
    await db.add_play("id2", "Artist2", "Title2")
    plays = await db.recent_plays(limit=5)
    assert len(plays) == 2
    assert plays[0]["spotify_id"] == "id2"
    ids = await db.recent_spotify_ids(hours=24)
    assert {"id1", "id2"}.issubset(ids)


@pytest.mark.asyncio
async def test_script_history():
    await db.init_db()
    await db.add_script("chat", "本文1", "要約1")
    await db.add_script("intro", "本文2", "要約2")
    summaries = await db.recent_summaries(limit=10)
    assert len(summaries) == 2


@pytest.mark.asyncio
async def test_cache_put_get():
    await db.init_db()
    await db.cache_put("test_kind", "key1", {"hello": "world"}, ttl_seconds=60)
    got = await db.cache_get("test_kind", "key1")
    assert got == {"hello": "world"}


@pytest.mark.asyncio
async def test_cache_expired():
    await db.init_db()
    await db.cache_put("test_kind", "key2", "value", ttl_seconds=-1)
    got = await db.cache_get("test_kind", "key2")
    assert got is None


@pytest.mark.asyncio
async def test_cache_invalidate_kind():
    await db.init_db()
    await db.cache_put("kindA", "k1", "v1", ttl_seconds=600)
    await db.cache_put("kindB", "k2", "v2", ttl_seconds=600)
    await db.cache_invalidate_kind("kindA")
    assert await db.cache_get("kindA", "k1") is None
    assert await db.cache_get("kindB", "k2") == "v2"


@pytest.mark.asyncio
async def test_mark_mail_status():
    await db.init_db()
    mid = await db.add_mail("a", "b", None, False)
    await db.mark_mail(mid, "read")
    rows = await db.list_mails(limit=10)
    assert rows[0]["status"] == "read"
