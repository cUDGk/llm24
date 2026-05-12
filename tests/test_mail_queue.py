"""お便りキューの単体テスト。"""

import pytest

from server import db, mail_queue


@pytest.mark.asyncio
async def test_force_always_picked():
    await db.init_db()
    fid = await db.add_mail("a", "force", None, True)
    await db.add_mail("b", "normal", None, False)
    m = await mail_queue.pick_next_mail("when_full", -10, 0)
    assert m is not None
    assert m["id"] == fid


@pytest.mark.asyncio
async def test_every_picks_normal():
    await db.init_db()
    nid = await db.add_mail("a", "msg", None, False)
    m = await mail_queue.pick_next_mail("every", -10, 0)
    assert m is not None and m["id"] == nid


@pytest.mark.asyncio
async def test_every_few_skips_when_recent():
    await db.init_db()
    await db.add_mail("a", "msg", None, False)
    m = await mail_queue.pick_next_mail("every_few", 5, 6)  # gap=1, < 3
    assert m is None


@pytest.mark.asyncio
async def test_every_few_picks_after_gap():
    await db.init_db()
    await db.add_mail("a", "msg", None, False)
    m = await mail_queue.pick_next_mail("every_few", 5, 8)  # gap=3
    assert m is not None


@pytest.mark.asyncio
async def test_when_full_threshold():
    await db.init_db()
    for i in range(5):
        await db.add_mail(f"u{i}", f"msg{i}", None, False)
    m = await mail_queue.pick_next_mail("when_full", -10, 0)
    assert m is not None


@pytest.mark.asyncio
async def test_consume_mail():
    await db.init_db()
    mid = await db.add_mail("a", "msg", None, False)
    await mail_queue.consume_mail(mid)
    rows = await db.list_mails(status="consumed", limit=10)
    assert any(r["id"] == mid for r in rows)
