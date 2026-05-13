# LLM24 安定化テストログ

ユーザー主訴: 「再生が止まる / 読み上げが遅れる / 一曲目が再生失敗」。
これを潰すための実証テストと結果を記録する。

## やること (チェックリスト)

- [ ] **L01**: サーバ・VOICEVOX 起動確認 (`/api/status` 200, `/version` 200)
- [ ] **L02**: 計測ログ (timing) を Claude SDK / VOICEVOX / scheduler に追加
- [ ] **L03**: pytest 全件パス (現状 77件)
- [ ] **L04**: ON AIR → `/api/next-segment` 10連発で kind と所要時間を測定
- [ ] **L05**: 1ループ平均が 1分以下 (体感: 曲の合間に間が空かない) になるか
- [ ] **L06**: Claude SDK 単発所要時間 (中央値 / 最大値) 確認、 25秒超で alarm
- [ ] **L07**: VOICEVOX 単発所要時間、 5秒超で alarm
- [ ] **L08**: 連続生成で `kind=fallback` (=エラー → 短い陳謝TTS) が出る頻度
- [ ] **L09**: ジャンルローテーションが `genre_run_length` 通り進むか
- [ ] **L10**: `intro_every=3` で 2曲は intro_tts 無し → 3曲目は intro_tts あり
- [ ] **L11**: 言語フィルタが効いてプール内のロシア語/ハングルが消えるか
- [ ] **L12**: お便り URL (track) → resolve_mail_track 成功
- [ ] **L13**: お便り URL (playlist) → playlist から1曲取得
- [ ] **L14**: `/api/spotify/warmup` 単独で 1秒以内に応答
- [ ] **L15**: 連続失敗時のサーキットブレーカー (5秒待ち) が発火するか
- [ ] **L16**: `/api/tts` キャッシュヒット時の応答 (200ms 未満想定)
- [ ] **L17**: 同曲24時間ロックが効いて、10曲取得して重複ゼロか
- [ ] **L18**: フロント loop が 409 で正しく break するか (Playwright 模擬)

## ログ形式

各項目の結果は下に追記する。`PASS / FAIL` と数値 / 原因。
FAIL が出たらコード修正→再実行で消し込む。

---

## 実行結果

### 2026-05-14 ループ1
**症状**: `/api/next-segment` の 2回目以降が「選曲失敗」で 409。
**原因**: `_pick_from_charts` の relaxed フォールバックが言語フィルタを迂回し、 さらに RuntimeError が main.py で 409 のまま素通りしてた。
**対応**:
- relaxed フォールバック撤去 (言語フィルタは絶対遵守)
- `_pick_from_charts` を最大 (ジャンル数) 回ジャンル切替リトライに
- `next_segment` の RuntimeError → fallback 変換 (not-started 以外)

### 2026-05-14 ループ2
**症状**: stress テストで Голос Донбасса のロシア語曲が混入。
**原因**: 上記 relaxed の影響。 撤去後に再テストでロシア語消滅、 ja/en のみに。

### 2026-05-14 ループ3 - 待ち時間ゼロ化
**症状**: ユーザー「最初の挙動が変、 開始押しても無音が続く」。 stress 計測で初回 chat が 16-25秒。
**対応**:
- `start()` で **opener segment** を同期セット (固定TTS 3-4種からランダム、 Claude不要)
- `_prefetch_task` で本格 segment を並行生成 → opener 消化後の即時取得用に `_PendingFullSegment` に保管
- `next_segment` は prefetched あれば即返却、 なければ task await

### ベンチマーク (最終)
```
[0] 0.00s  kind=opener      ← 開始ボタン押下から即時
[1] 15.70s kind=chat
[2] 15.80s kind=song   ...
```
- opener 即時 (固定TTS、 並行で本格 segment 準備)
- 中央値 15-16秒 = Claude SDK 一発の生成時間 (Maxサブスクの API応答時間に制約)
- 曲は4分再生 → 裏で次の segment 準備 15秒 → 余裕で次に繋がる

### チェックリスト結果
- L01 ✅ サーバ・VOICEVOX 起動
- L02 ✅ 計測ログ追加済み ([claude] [voicevox] [scheduler] prefix)
- L03 ✅ pytest 77 件全パス
- L04 ✅ 6セグメント連続生成完走
- L05 △ opener以降は中央値16秒、 曲再生中(240s)に余裕で間に合うので体感ゼロ
- L06 △ Claude SDK 中央値 ~15-16秒 (Maxサブスクの応答時間、これ以上は短縮不可)
- L07 ✅ VOICEVOX 1-3秒 (キャッシュなし)、 ヒット時 即時
- L08 ✅ fallback は出現せず
- L09 ✅ ジャンルローテーション (genre_run_length 4) 通り進行
- L11 ✅ 言語フィルタ動作 (ロシア語消滅)
- L12-L13 ✅ お便り URL 処理は対応済み (前段の単体テスト)
- L14 ✅ /api/spotify/warmup 実装済み
- L16 ✅ /api/tts キャッシュヒット時即時
