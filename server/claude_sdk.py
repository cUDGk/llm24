"""Claude Code SDK (claude-agent-sdk) ラッパー。

Claude Code Max サブスクの認証を流用して、台本生成と選曲を行う。

役割:
- 曲紹介台本 (intro)
- 雑談台本 (chat)
- お便り反応台本 (mail)
- 選曲 (pick)
"""

from __future__ import annotations

import asyncio
import json
import re
from typing import Any

from claude_agent_sdk import ClaudeAgentOptions, query


CLAUDE_TIMEOUT_SECONDS = 45.0


SYSTEM_BASE = """\
あなたはローカル AI ラジオ番組「LLM24」の台本生成 AI です。
番組の方針:
- DJ は常に男性。ハイテンションは禁止。番組全体「ゆるい」基調で統一。
- 30分中トークは約3分。簡潔に、しゃべりすぎない。
- 出力は必ず指定 JSON 形式のみ。前置きや解説、コードフェンス、絵文字を入れない。

読み上げ用テキストの重要ルール (VOICEVOX 日本語TTS):
- 英語表記のアーティスト名・曲名は **カタカナ表記** に書き換えて出力する。
  ローマ字を一文字ずつ読まれるのを避けるため。
  例: Mrs. GREEN APPLE → ミセスグリーンアップル / King Gnu → キングヌー /
      YOASOBI → ヨアソビ / Vaundy → バウンディ / Official髭男dism → オフィシャル髭男ディズム /
      back number → バックナンバー / Kenshi Yonezu → 米津玄師 (漢字) /
      Mr.Children → ミスターチルドレン / Spitz → スピッツ
- 一般的な英単語 (例: rock, pop) もカタカナで表記する。
- 数字は読み上げ通りに (12時 → じゅうにじ、ではなく "12時" のままでよい)。
- 半角記号 (-, /, &, etc.) は読み上げない、文字で書かない。
"""


def _build_options(extra_system: str = "") -> ClaudeAgentOptions:
    sys_prompt = SYSTEM_BASE
    if extra_system:
        sys_prompt += "\n\n" + extra_system
    return ClaudeAgentOptions(
        system_prompt=sys_prompt,
        max_turns=1,
        allowed_tools=[],
    )


async def _ask_inner(prompt: str, system_extra: str = "") -> str:
    options = _build_options(system_extra)
    chunks: list[str] = []
    async for message in query(prompt=prompt, options=options):
        content = getattr(message, "content", None)
        if content is None:
            continue
        if isinstance(content, str):
            chunks.append(content)
            continue
        if isinstance(content, list):
            for block in content:
                text = getattr(block, "text", None)
                if text:
                    chunks.append(text)
    return "".join(chunks).strip()


async def _ask(prompt: str, system_extra: str = "") -> str:
    """Claude に1ターン投げてテキストを取り出す。タイムアウト付き。"""
    try:
        return await asyncio.wait_for(_ask_inner(prompt, system_extra), timeout=CLAUDE_TIMEOUT_SECONDS)
    except asyncio.TimeoutError:
        raise RuntimeError(f"Claude SDK timed out after {CLAUDE_TIMEOUT_SECONDS}s")


def _extract_json(raw: str) -> dict[str, Any]:
    """Claudeが余計な前置きを付けた場合に備えて、最初の { から最後の } を切り出す。"""
    raw = raw.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", raw, re.DOTALL)
    if fence:
        return json.loads(fence.group(1))
    start = raw.find("{")
    end = raw.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise ValueError(f"Claude応答からJSON抽出失敗: {raw[:200]}")
    return json.loads(raw[start : end + 1])


# ---------------------------------------------------------------- 台本系

def _now_context() -> str:
    from datetime import datetime
    n = datetime.now()
    weekday = ["月", "火", "水", "木", "金", "土", "日"][n.weekday()]
    return f"現在時刻: {n.year}年{n.month}月{n.day}日({weekday}) {n.hour}時{n.minute:02d}分"


async def gen_song_intro(
    *,
    persona_desc: str,
    artist: str,
    title: str,
    related_mail: dict | None,
    recent_summaries: list[str],
) -> dict[str, Any]:
    """曲振り台本を生成。"""
    mail_part = ""
    if related_mail:
        mail_part = (
            f"\n直前に読んだお便り: ラジオネーム「{related_mail['radio_name']}」"
            f" 本文「{related_mail['body']}」 リクエスト「{related_mail.get('request') or '(なし)'}」"
            f"\n→ これに絡めて曲振り。「リクエストで」のニュアンスを自然に入れる。"
        )

    summaries = "\n".join(f"- {s}" for s in recent_summaries[:10]) or "(なし)"
    prompt = f"""\
{_now_context()}

時間帯ペルソナ:
{persona_desc}

次の曲: {artist} の「{title}」

直近の台本要約 (重複禁止・同じ言い回しを避ける):
{summaries}
{mail_part}

要件:
- 約20秒で読める長さ (日本語で 80〜120 文字程度)
- 「次の曲は◯◯の△△」型を基本としつつ、自然な崩しを混ぜる
- 過度な情緒・絶賛・煽り禁止
- 季節・時間帯・曜日に矛盾しない発言にする (上記「現在時刻」に従う)
- 出力は次のJSONのみ:
{{"text": "<読み上げ用テキスト>", "summary": "<10〜20文字の要約>"}}
"""
    raw = await _ask(prompt)
    return _extract_json(raw)


async def gen_chat(
    *,
    persona_desc: str,
    last_played: list[dict],
    recent_summaries: list[str],
    extra_topic: str = "",
) -> dict[str, Any]:
    """雑談台本を生成 (お便りがない場合の繋ぎ)。"""
    plays = "\n".join(f"- {p['artist']} / {p['title']}" for p in last_played[:5]) or "(なし)"
    summaries = "\n".join(f"- {s}" for s in recent_summaries[:10]) or "(なし)"
    prompt = f"""\
{_now_context()}

時間帯ペルソナ:
{persona_desc}

直近の選曲:
{plays}

直近の台本要約 (重複禁止):
{summaries}

雑談ネタの方向性:
- 直前曲の感想・関連エピソード
- 時間帯ネタ (深夜なら寝てる人へのぼやき など)
- 完全な独り言・脱線・哲学・好きな食べ物

{('追加トピック: ' + extra_topic) if extra_topic else ''}

要件:
- 約60秒で読める長さ (日本語で 200〜260 文字程度)
- 句読点で区切り、TTSが息継ぎしやすい構造
- 同じ話題を繰り返さない
- 季節・時間帯・曜日と矛盾する発言はしない (上記「現在時刻」に従う)
- 出力は次のJSONのみ:
{{"text": "<読み上げ用>", "summary": "<10〜20文字の要約>"}}
"""
    raw = await _ask(prompt)
    return _extract_json(raw)


async def gen_mail_reply(
    *,
    persona_desc: str,
    mail: dict,
    recent_summaries: list[str],
) -> dict[str, Any]:
    """お便り読み上げ + DJ反応コメント。"""
    summaries = "\n".join(f"- {s}" for s in recent_summaries[:10]) or "(なし)"
    prompt = f"""\
{_now_context()}

時間帯ペルソナ:
{persona_desc}

お便り:
- ラジオネーム: {mail['radio_name']}
- 本文: {mail['body']}
- リクエスト: {mail.get('request') or '(なし)'}
- force(必ず反映): {bool(mail.get('force'))}

直近の台本要約 (重複禁止):
{summaries}

要件:
- ラジオネーム読み上げ → 本文を要約しながら朗読 → DJ反応コメント
- 全体で30〜60秒 (日本語120〜220文字程度)
- 反応はゆるく、共感寄り。茶化しすぎない。
- 出力は次のJSONのみ:
{{"text": "<読み上げ用>", "summary": "<10〜20文字の要約>"}}
"""
    raw = await _ask(prompt)
    return _extract_json(raw)


# ---------------------------------------------------------------- 選曲

async def pick_song(
    *,
    persona_desc: str,
    genres: list[str],
    excludes: dict[str, list[str]],
    recent: list[dict],
    active_mail: dict | None,
) -> dict[str, Any]:
    """次の1曲を Claude に選ばせる。

    Returns: {"artist": str, "title": str, "reason": str}
    """
    recent_lines = "\n".join(f"- {p['artist']} / {p['title']}" for p in recent[:20]) or "(なし)"
    ex_a = ", ".join(excludes.get("artists", [])) or "(なし)"
    ex_g = ", ".join(excludes.get("genres", [])) or "(なし)"
    ex_k = ", ".join(excludes.get("keywords", [])) or "(なし)"

    mail_part = ""
    if active_mail:
        mail_part = (
            f"\nアクティブなお便り (force={bool(active_mail.get('force'))}):"
            f"\n  ラジオネーム: {active_mail['radio_name']}"
            f"\n  リクエスト: {active_mail.get('request') or active_mail['body']}"
        )
        if active_mail.get("force"):
            mail_part += "\n→ force=true。リクエスト内容に **必ず** 合う曲を選ぶこと。"
        else:
            mail_part += "\n→ force=false。リクエストを軽く反映する程度でよい。"

    prompt = f"""\
時間帯ペルソナ:
{persona_desc}

希望ジャンル: {", ".join(genres) or "指定なし"}

除外アーティスト: {ex_a}
除外ジャンル: {ex_g}
除外キーワード: {ex_k}

直近の再生履歴 (重複禁止):
{recent_lines}
{mail_part}

次にかける1曲を「Spotify で確実に検索ヒットするアーティスト・曲名」で1つだけ選ぶ。

要件:
- 上の除外と重複を絶対避ける
- 同じアーティストを3曲連続させない
- 出力は次のJSONのみ:
{{"artist": "<アーティスト名>", "title": "<曲名>", "reason": "<選んだ理由 30文字以内>"}}
"""
    raw = await _ask(prompt)
    return _extract_json(raw)
