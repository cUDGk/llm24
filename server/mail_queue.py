"""お便りキューの処理。

- force=True: キュー先頭に優先、次の選曲タイミングで即消化、リクエストを曲選定に必須反映
- force=False: 採用率設定に従って間引き、リクエストは曲調にソフト反映
"""

from __future__ import annotations

from typing import Any

from . import db


async def pick_next_mail(adoption: str, last_mail_index: int, idx: int) -> dict[str, Any] | None:
    """次の30分枠でお便りを採用するか決め、対象お便りを返す。

    Args:
        adoption: "every" / "every_few" / "when_full"
        last_mail_index: 直近で読み上げた idx（採用率制御用）
        idx: 現在の枠インデックス
    Returns:
        お便り行 or None
    """
    force = await db.pop_force_mail()
    if force:
        return force

    if adoption == "every":
        should_read = True
    elif adoption == "every_few":
        should_read = (idx - last_mail_index) >= 3
    else:  # when_full
        mails = await db.list_mails(status="queued", limit=10)
        normal_mails = [m for m in mails if not m["force"]]
        should_read = len(normal_mails) >= 5

    if not should_read:
        return None

    return await db.pop_normal_mail()


async def consume_mail(mail_id: int) -> None:
    await db.mark_mail(mail_id, "consumed")


async def mark_read(mail_id: int) -> None:
    await db.mark_mail(mail_id, "read")
