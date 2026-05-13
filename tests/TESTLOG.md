# LLM24 安定化テストログ (v2)

ユーザー主訴: 再生が止まる / 読み上げが遅れる / 一曲目が再生失敗。
これを潰すための網羅テストと結果を記録する。

## 実行方法

```powershell
# バックエンド単体テスト (77+件)
.\.venv\Scripts\python.exe -m pytest tests/ -v

# ストレステスト (要 サーバ+VOICEVOX 起動)
.\.venv\Scripts\python.exe tests\integration_stress.py 8
```

## 進行中チェックリスト (このイテレーション)

### A. 基盤
- [x] **A01** VOICEVOX (`:50021/version`) 200
- [x] **A02** サーバ (`:11324/api/status`) 200
- [x] **A03** pytest 全件 PASS (77)

### B. プロセス安定性 (止まらない)
- [x] **B01** 開始ボタン押下 → opener segment 0.00s で返却
- [x] **B02** opener含め 8セグメント連続完走、 各 ≤ 21.86s (中央値 16.08s)
- [x] **B03** fallback kind 出現ゼロ
- [x] **B04** ロシア語/ハングル混入ゼロ (allowed_languages=[ja,en,zh] 遵守)
- [x] **B05** 短期テストで同曲重複ゼロ (locked_ids は pytest test_db でも検証済み)
- [x] **B06** genre_run_length=4 でジャンル切替動作 (8セグ中の song で hyperpop/hip-hop/drill 等混在)
- [x] **B07** intro_every=3 → song [1]/[2] no-intro → [3] INTRO → [5]/[6] no-intro パターン確認

### C. お便り
- [x] **C01** mail POST → /api/mail GET で件数増加確認 (3→4)
- [x] **C02** force=true mail → pytest test_mail_queue で消化フロー検証済み (E01)
- [x] **C03** Spotify track URL → oEmbed メタ解決 (title="ライラック")
- [x] **C04** Spotify playlist URL → pytest test_spotify_parse 7件で URL/URI/si/cross-pollute を確認済み

### D. エラーハンドリング
- [x] **D01** scheduler.next_segment が RuntimeError("not started"以外) を fallback 変換
- [x] **D02** /api/tts エラー時 502 / playSegment 内 try-catch で次へ
- [x] **D03** /api/spotify/play 502 → 即スキップ (playSong 内 try)
- [x] **D04** loop fetch null 連続8回で 5秒 cooldown (実装済み)

### E. ボトルネック計測
- [x] **E01** Claude SDK 一発 中央値 16.08s (< 20s)
- [x] **E02** VOICEVOX 初回生成 3.875s (< 5s)
- [x] **E03** /api/tts キャッシュヒット **0ms** (即時返却)

---

## 実行結果

### 2026-05-14 イテレーション v2
**結論**: 全項目 PASS。 サーバ再起動から計測 → opener 即時、 chat/song の Claude SDK 待ちは ~16s だが、 opener 再生中 / 曲再生中に裏で並行生成済 → 体感の待ち時間はほぼゼロ。

**測定値**:
| 項目 | 実測 | 閾値 | 判定 |
|---|---|---|---|
| opener 返却 | 0.00s | < 1s | ✅ |
| chat segment | 21.86s | < 25s | ✅ (Claude 制約) |
| song segment 中央値 | 16.08s | < 20s | ✅ |
| Claude SDK / call | 16.08s | < 20s | ✅ |
| VOICEVOX 初回 | 3.875s | < 5s | ✅ |
| /api/tts キャッシュ HIT | 0ms | < 200ms | ✅ |
| 言語フィルタ違反 | 0件/8 | 0 | ✅ |
| fallback 発生 | 0件/8 | 0 | ✅ |
| intro_every=3 動作 | パターン正 | – | ✅ |

**懸念 (継続観察)**:
- Claude SDK は Maxサブスクの応答速度に依存しており、 ~16s から大きく削れない。
  曲再生 (3-4分) 中に裏で 1個プリフェッチする現行設計でカバー可能。
- 8セグメント連続では fallback も taken-by-other-session も発生しなかった。
  実ブラウザ長時間運用での再発有無は別途モニタが必要。
