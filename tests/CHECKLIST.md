# LLM24 動作チェックリスト

このプロジェクトの全動作確認項目。チェック内容はコードに対応するテストで自動検証する。

## 実行方法

```powershell
# バックエンド全テスト (54+件、目安10秒)
.\.venv\Scripts\python.exe -m pytest tests/ -v

# 個別テストファイル
.\.venv\Scripts\python.exe -m pytest tests/test_api.py -v
```

フロントエンドは Playwright MCP で対話的に検証 (Spotify Web Playback SDK は Widevine 必須のため、Playwright Chromium では再生APIまで通せない)。
実ブラウザでは <http://127.0.0.1:11324/> を開いて手動で「FE手動」項目を確認する。

---

## A. バックエンド API (`tests/test_api.py`)

| ID  | 項目                                              | 確認                                                   |
| --- | ------------------------------------------------- | ------------------------------------------------------ |
| A01 | `GET /` が 200 を返す                              | `test_index_html`                                      |
| A02 | `/static/style.css` が 200                        | `test_static_css`                                      |
| A03 | `/static/app.js` が 200                           | `test_static_js`                                       |
| A04 | `/api/status` が `on_air/spotify_authenticated` 返す | `test_status_not_on_air`                              |
| A05 | Spotify未認証時 `/api/onair` が 401                | `test_onair_without_spotify`                           |
| A06 | `/api/settings` GET / PUT                         | `test_settings_get_put`                                |
| A07 | `/api/mail` POST + GET                            | `test_mail_post_get`                                   |
| A08 | mail バリデーション (radio_name 長すぎ)             | `test_mail_validation_too_long`                        |
| A09 | mail バリデーション (空 radio_name)                 | `test_mail_validation_empty_name`                      |
| A10 | `/api/clientlog` POST                             | `test_clientlog`                                       |
| A11 | OFF AIR 時 `/api/next-segment` が 409              | `test_next_segment_not_on_air`                         |
| A12 | ON AIR → next-segment → OFF AIR の一周              | `test_onair_flow_with_mocked_segment`                  |
| A13 | `/api/spotify/token` 未認証 401                    | `test_spotify_token_unauthenticated`                   |
| A14 | `/api/spotify/play` device未登録 400               | `test_spotify_play_no_device`                          |
| A15 | `/api/spotify/device` 登録 → server保持             | `test_spotify_device_register`                         |

## B. Spotify URL 解析 (`tests/test_spotify_parse.py`)

| ID  | 項目                                       | 確認                          |
| --- | ------------------------------------------ | ----------------------------- |
| B01 | `open.spotify.com/track/<22>` 形式抽出      | `test_open_url`               |
| B02 | `?si=...` 付き URL                          | `test_open_url_with_si`       |
| B03 | `intl-ja/track/...` 国際版 URL              | `test_open_url_intl_jp`       |
| B04 | `spotify:track:<22>` URI                    | `test_uri`                    |
| B05 | 無関係 URL は None                          | `test_invalid_url`            |
| B06 | 空文字 / None                               | `test_empty`                  |
| B07 | album URL は track id とみなさない          | `test_album_url_not_track`    |

## C. ペルソナ (`tests/test_persona.py`)

| ID  | 項目                                | 確認                                |
| --- | ----------------------------------- | ----------------------------------- |
| C01 | 0-5時 → midnight                    | `test_midnight`                     |
| C02 | 5-11時 → morning                    | `test_morning`                      |
| C03 | 11-17時 → noon                      | `test_noon`                         |
| C04 | 17-24時 → evening                   | `test_evening`                      |
| C05 | 境界 (0:00) midnight                | `test_boundary_midnight_start`      |
| C06 | 境界 (5:00) morning                  | `test_boundary_morning_start`       |
| C07 | 未知 slot で KeyError                | `test_find_unknown`                 |

## D. DB アクセス層 (`tests/test_db.py`)

| ID  | 項目                                      | 確認                                |
| --- | ----------------------------------------- | ----------------------------------- |
| D01 | init_db + add_mail + list_mails           | `test_init_and_add_mail`            |
| D02 | force mail 先頭で pop / 通常も pop        | `test_pop_force_mail`               |
| D03 | play_history 追加 / 直近20件取得           | `test_play_history`                 |
| D04 | script_history 追加 / summary 取得         | `test_script_history`               |
| D05 | spotify_cache put → get                   | `test_cache_put_get`                |
| D06 | 期限切れ cache は None                     | `test_cache_expired`                |
| D07 | kind 単位の cache 無効化                   | `test_cache_invalidate_kind`        |
| D08 | mail status 更新                           | `test_mark_mail_status`             |

## E. メールキュー (`tests/test_mail_queue.py`)

| ID  | 項目                                            | 確認                                  |
| --- | ----------------------------------------------- | ------------------------------------- |
| E01 | force=true は採用率に関係なく拾われる            | `test_force_always_picked`            |
| E02 | adoption=every で通常mailも拾う                  | `test_every_picks_normal`             |
| E03 | every_few で直近に読んだら採用しない             | `test_every_few_skips_when_recent`    |
| E04 | every_few でギャップ超えたら採用                 | `test_every_few_picks_after_gap`      |
| E05 | when_full で閾値超えたら採用                     | `test_when_full_threshold`            |
| E06 | consume で status=consumed                      | `test_consume_mail`                   |

## F. 設定ストア (`tests/test_settings.py`)

| ID  | 項目                                         | 確認                                |
| --- | -------------------------------------------- | ----------------------------------- |
| F01 | デフォルト値読み出し (genres/seed_artists)   | `test_defaults_load`                |
| F02 | update が JSON に永続化される                | `test_update_persists`              |
| F03 | 部分更新でデフォルトが残る                    | `test_partial_update_keeps_defaults`|

## G. スケジューラ (`tests/test_scheduler.py`)

| ID  | 項目                                                          | 確認                                          |
| --- | ------------------------------------------------------------- | --------------------------------------------- |
| G01 | _floor_to_half_hour が 0/30 にスナップ                         | `test_floor_to_half_hour`                     |
| G02 | 初回 _should_play_time_signal は False で last 初期化           | `test_should_play_time_signal_first_call_resets` |
| G03 | 30分跨ぎで True                                                | `test_should_play_time_signal_crosses_half_hour` |
| G04 | mail.request の Spotify URL → oEmbed + search で メタ取得      | `test_resolve_mail_track_with_url`            |
| G05 | request 無し → None                                            | `test_resolve_mail_track_no_request`          |
| G06 | 無関係URL → None                                                | `test_resolve_mail_track_invalid_url`         |
| G07 | プールから1曲選曲                                              | `test_pick_from_charts_returns_track`         |
| G08 | exclude.keywords で曲名フィルタが効く                          | `test_pick_from_charts_excludes_keyword`      |

---

## J. Spotify 実API統合 (`tests/test_spotify_integration.py`)

`data/.spotify_token.json` がある時に実 Spotify Web API を叩いて確認。
無ければ自動 skip。ブラウザを介さずに Spotify 接続を担保する。

| ID  | 項目                                          | 確認                                          |
| --- | --------------------------------------------- | --------------------------------------------- |
| J01 | access_token 取得 (期限切れなら自動refresh)    | `test_get_access_token`                       |
| J02 | /me プロフィール取得 (product 値あり)          | `test_user_profile_has_product`               |
| J03 | is_premium() が bool 返す                      | `test_is_premium_returns_bool`                |
| J04 | アーティスト top tracks (Mrs. GREEN APPLE)     | `test_artist_top_tracks_mrs_green_apple`      |
| J05 | ジャンル検索 (シティポップ)                    | `test_search_by_genre_returns_tracks`         |
| J06 | oEmbed で track title + thumbnail              | `test_track_oembed_returns_title`             |
| J07 | フリーテキスト track 検索                       | `test_search_by_track_query`                  |

## H. フロント UI (Playwright MCP で対話確認)

| ID  | 項目                                                       | 確認方法                                          |
| --- | ---------------------------------------------------------- | ------------------------------------------------- |
| H01 | / にアクセスで `LLM24` タイトル                             | playwright snapshot で確認                        |
| H02 | コンソールエラー 0 (Widevine無しの SDK error は除外)       | `browser_console_messages`                        |
| H03 | JA → EN トグルでヘッダー/各ラベルが英語                     | snapshot 比較                                     |
| H04 | EN → JA で日本語復帰                                       | snapshot 比較                                     |
| H05 | 投函済みリストのタグ (未読/読了) も言語追従                  | snapshot 比較                                     |
| H06 | 開始/停止 1ボタン切替                                        | `btn-toggle` クリック → label 反転                 |
| H07 | ボタン disabled 制御 (処理中は反応無効)                     | snapshot                                          |
| H08 | アルバムアートが新トラックで更新される                       | playSong 後 `np-art` src が変わる                 |
| H09 | プログレスバー + 残り時間表示                                | song 再生中の `#progress-bar` width 変化          |
| H10 | 次の曲プレビュー (プリフェッチ済の時)                        | `#next-up` 表示                                    |
| H11 | お便りフォーム POST → リストに即時追加                       | submit → `#mail-list` に新項目                    |
| H12 | リクエスト欄: 非Spotify URLで弾く                            | 不正URL入力 → error 表示                          |
| H13 | 設定保存 → サーバ反映 → 再読込で保持                        | PUT 200 + GET で値一致                            |
| H14 | ライトモードのみ (CSS variables = light palette)             | css 読込で `--bg: #f5f4f1`                        |
| H15 | 設定UIに「推しアーティスト」入力欄あり、保存反映              | `#s-seed-art` 値が PUT/GET で一致                  |
| H16 | ログイン成功後は SPOTIFY ログイン ボタンが必ず hidden        | `#btn-spotify-login.hidden === true`              |
| H17 | Claude プロンプトに現在時刻 (年月日時分+曜日) を含む          | `claude_sdk._now_context()` 単体確認              |

## I. 実ブラウザ確認 (FE手動)

Playwright Chromium では Widevine 非対応のため、以下は実Chrome/Edge/Brave で確認する。

| ID  | 項目                                                       |
| --- | ---------------------------------------------------------- |
| I01 | Premium判定: `Premium未確認` バッジ非表示 (加入時)         |
| I02 | Spotifyログインフロー (`/auth/spotify` → 戻り)              |
| I03 | 開始 → 数秒以内に曲振り TTS → 曲再生                        |
| I04 | 曲再生中 イントロ被せでSpotify音量ダッキング                |
| I05 | 曲終了 → 次セグメント (無音時間ほぼゼロ)                    |
| I06 | 停止ボタン → フェードアウト + 880Hz × 3                     |
| I07 | お便り投函 (FORCE + Spotify URL) → 次曲でリクエスト曲再生  |
| I08 | 時報枠 (00分 / 30分) で時報セグメント発生                   |

---

## 最新実行結果

直近の `pytest tests/ -v` 実行で `61 passed` (実行時間 ~15秒)。
内訳: A〜G の単体/モック 54件 + J Spotify実API 7件。
失敗が出たらここに記録して、修正コミットで再実行する。
