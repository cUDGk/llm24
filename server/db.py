"""SQLite アクセス層。

スキーマ:
- mails:          お便り
- play_history:   再生履歴
- script_history: 台本履歴
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

import aiosqlite

from .config import DB_PATH


SCHEMA = """
CREATE TABLE IF NOT EXISTS mails (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    radio_name  TEXT NOT NULL,
    body        TEXT NOT NULL,
    request     TEXT,
    force       INTEGER NOT NULL DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'queued',
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_mails_status ON mails(status);
CREATE INDEX IF NOT EXISTS idx_mails_force_status ON mails(force, status);

CREATE TABLE IF NOT EXISTS play_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    spotify_id  TEXT NOT NULL,
    artist      TEXT NOT NULL,
    title       TEXT NOT NULL,
    played_at   TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_play_history_played_at ON play_history(played_at DESC);
CREATE INDEX IF NOT EXISTS idx_play_history_spotify_id ON play_history(spotify_id);

CREATE TABLE IF NOT EXISTS script_history (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    kind        TEXT NOT NULL,
    content     TEXT NOT NULL,
    summary     TEXT,
    created_at  TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_script_history_created_at ON script_history(created_at DESC);
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()


# ---- mails ----

async def add_mail(radio_name: str, body: str, request: str | None, force: bool) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT INTO mails(radio_name, body, request, force, status, created_at) "
            "VALUES(?, ?, ?, ?, 'queued', ?)",
            (radio_name, body, request, 1 if force else 0, _now_iso()),
        )
        await conn.commit()
        return cur.lastrowid


async def list_mails(status: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    sql = "SELECT id, radio_name, body, request, force, status, created_at FROM mails"
    params: tuple[Any, ...] = ()
    if status:
        sql += " WHERE status = ?"
        params = (status,)
    sql += " ORDER BY id DESC LIMIT ?"
    params = (*params, limit)
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(sql, params) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def pop_force_mail() -> dict[str, Any] | None:
    """キューにある force=1 のお便りを1件取得（取得しただけ。status変更は別途）。"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, radio_name, body, request, force, status, created_at "
            "FROM mails WHERE force = 1 AND status = 'queued' "
            "ORDER BY id ASC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def pop_normal_mail() -> dict[str, Any] | None:
    """queued な通常お便りを1件。"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, radio_name, body, request, force, status, created_at "
            "FROM mails WHERE force = 0 AND status = 'queued' "
            "ORDER BY id ASC LIMIT 1"
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None


async def mark_mail(mail_id: int, status: str) -> None:
    async with aiosqlite.connect(DB_PATH) as conn:
        await conn.execute("UPDATE mails SET status = ? WHERE id = ?", (status, mail_id))
        await conn.commit()


# ---- play_history ----

async def add_play(spotify_id: str, artist: str, title: str) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT INTO play_history(spotify_id, artist, title, played_at) VALUES(?, ?, ?, ?)",
            (spotify_id, artist, title, _now_iso()),
        )
        await conn.commit()
        return cur.lastrowid


async def recent_plays(limit: int = 20) -> list[dict[str, Any]]:
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, spotify_id, artist, title, played_at FROM play_history "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]


async def recent_spotify_ids(hours: int = 24) -> set[str]:
    """過去N時間に再生した曲のSpotify IDセット（同曲ロック用）。"""
    async with aiosqlite.connect(DB_PATH) as conn:
        async with conn.execute(
            "SELECT spotify_id FROM play_history "
            "WHERE played_at > datetime('now', ?)",
            (f"-{hours} hours",),
        ) as cur:
            rows = await cur.fetchall()
            return {r[0] for r in rows}


# ---- script_history ----

async def add_script(kind: str, content: str, summary: str | None) -> int:
    async with aiosqlite.connect(DB_PATH) as conn:
        cur = await conn.execute(
            "INSERT INTO script_history(kind, content, summary, created_at) VALUES(?, ?, ?, ?)",
            (kind, content, summary, _now_iso()),
        )
        await conn.commit()
        return cur.lastrowid


async def recent_summaries(limit: int = 30) -> list[dict[str, Any]]:
    """直近の台本要約（重複防止に使う）。"""
    async with aiosqlite.connect(DB_PATH) as conn:
        conn.row_factory = aiosqlite.Row
        async with conn.execute(
            "SELECT id, kind, summary, content, created_at FROM script_history "
            "WHERE summary IS NOT NULL "
            "ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cur:
            return [dict(r) for r in await cur.fetchall()]
