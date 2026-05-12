"""時間帯別 DJ ペルソナ定義。"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


# VOICEVOX speaker_id (style_id) のメモ:
# - 13: 青山龍星 (ノーマル)  → 低音・渋い
# - 11: 玄野武宏 (ノーマル)  → 標準的
# - 53: 剣崎雌雄 (ノーマル)  → ゆるめ
# 参考: VOICEVOX の /speakers エンドポイントで実際のIDを確認できる。


@dataclass(frozen=True)
class Persona:
    slot: str
    label: str
    description: str
    default_speaker_id: int


MIDNIGHT = Persona(
    slot="midnight",
    label="深夜DJ",
    description=(
        "0時から5時の深夜帯。眠そうで、独り言が多い。哲学的な脱線をする。"
        "ハイテンションNG。誰かに話しかけるというより、深夜にぼんやり呟いてる感じ。"
    ),
    default_speaker_id=13,
)

MORNING = Persona(
    slot="morning",
    label="朝DJ",
    description=(
        "5時から11時の朝帯。寝起き感がまだ残っていてテンション低め。"
        "明るすぎず、しかし朝らしい穏やかさはある。コーヒー啜ってる感じ。"
    ),
    default_speaker_id=11,
)

NOON = Persona(
    slot="noon",
    label="昼DJ",
    description=(
        "11時から17時の昼帯。普通モード。気だるい雑談メインで、淡々と曲を回す。"
        "張り切らない。サラリーマンの昼休みに流れていても邪魔にならない声量感。"
    ),
    default_speaker_id=11,
)

EVENING = Persona(
    slot="evening",
    label="夕方〜夜DJ",
    description=(
        "17時から24時の夕方・夜帯。リラックスして落ち着いた声。"
        "1日の終わりを優しく見送る感じ。湯船に浸かりながら聞ける雰囲気。"
    ),
    default_speaker_id=53,
)


ALL_PERSONAS: list[Persona] = [MIDNIGHT, MORNING, NOON, EVENING]


def current_persona(now: datetime | None = None) -> Persona:
    h = (now or datetime.now()).hour
    if 0 <= h < 5:
        return MIDNIGHT
    if 5 <= h < 11:
        return MORNING
    if 11 <= h < 17:
        return NOON
    return EVENING


def find_persona(slot: str) -> Persona:
    for p in ALL_PERSONAS:
        if p.slot == slot:
            return p
    raise KeyError(f"unknown persona slot: {slot}")
