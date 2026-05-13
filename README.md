<div align="center">

# LLM24

### 24時間稼働する AI DJ ラジオ

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=flat&logo=python&logoColor=white)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115-009688?style=flat&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com/)
[![Spotify](https://img.shields.io/badge/Spotify-Web%20Playback%20SDK-1DB954?style=flat&logo=spotify&logoColor=white)](https://developer.spotify.com/documentation/web-playback-sdk)
[![VOICEVOX](https://img.shields.io/badge/VOICEVOX-Engine%200.25-41A2EC?style=flat)](https://voicevox.hiroshiba.jp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-green?style=flat)](LICENSE)

**台本も選曲も毎回 LLM 生成、 ローカルで完結する 24 時間ノンストップのパーソナル AI ラジオ**

---

</div>

## 概要

ローカル PC で立ち上げて、 ブラウザを Spotify Connect デバイスに変えて 24 時間流し続ける AI DJ ラジオ。 台本は LLM、 読み上げは VOICEVOX、 再生は Spotify Web Playback SDK でブラウザ自身が鳴らす。 設定はジャンル / 推しアーティスト / 言語フィルタ / 曲振り頻度 / 時間帯ペルソナまで自由にカスタム可能。

## 特徴

| 領域 | 内容 |
|---|---|
| 番組進行 | 30 分構成、 時報、 雑談、 曲振り、 お便りコーナー。 ジャンルローテーション (1 ジャンル N 曲ごと切替) |
| ペルソナ | 時間帯別 4 種 (深夜 / 朝 / 昼 / 夕方夜)。 男性 DJ ・ハイテンション禁止のゆるい基調 |
| 選曲 | ユーザー指定ジャンルから Spotify `genre:` フィルタ検索。 約 350 タグから候補入力補助、 自由入力可。 同曲 24h ロック、 連続同アーティスト制限、 除外キーワード対応 |
| 言語フィルタ | タイトル + アーティストの文字種で判定 (ja / en / ko / zh / ru / ar / th / hi)、 デフォルト ja + en |
| お便り | ラジオネーム + 本文 + Spotify track/playlist URL (任意)。 force フラグで次曲必ず反映。 投函済み一覧表示 |
| イントロ被せ | 曲開始と同時に DJ トーク TTS を被せて Spotify 音量を sine ease-in-out でダッキング |
| プリフェッチ | 曲再生中に裏で次セグメント生成。 開始直後は固定 opener TTS で待ち時間ゼロ化 |
| 停止 | フェードアウト → 880 Hz サイン波 × 3 → SDK disconnect で Spotify Connect から消える |
| UI | ライトモード固定、 1 画面完結、 アコーディオン設定、 ジャンルピッカー (350 タグ live フィルタ)、 字幕表示 |

## 構成

```
LLM24/
├── server/             # FastAPI バックエンド
│   ├── main.py         # エントリポイント・全エンドポイント
│   ├── scheduler.py    # 番組進行ループ・セグメント生成
│   ├── claude_sdk.py   # LLM 呼び出しラッパー (台本生成)
│   ├── spotify.py      # Spotify Web API クライアント (検索 / 再生制御 / oEmbed)
│   ├── voicevox.py     # VOICEVOX TTS クライアント (キャッシュ付き)
│   ├── persona.py      # 時間帯別ペルソナ
│   ├── mail_queue.py   # お便りキュー (force / 採用率)
│   ├── settings_store.py
│   └── db.py           # SQLite (mails / play_history / script_history / spotify_cache)
├── web/                # フロントエンド (素の HTML/CSS/JS)
│   ├── index.html
│   ├── app.js
│   ├── style.css
│   └── genres.json     # Spotify ジャンルタグ ≈350 件
├── tests/              # pytest 77 件 + 負荷テスト + CHECKLIST/TESTLOG
├── scripts/            # VOICEVOX セットアップ・ジングル生成
├── vendor/             # VOICEVOX エンジン解凍版 (gitignore 対象)
├── assets/             # 時報 / お便り / 番組 ID ジングル
└── data/               # SQLite / settings.json / TTS キャッシュ
```

## インストール

### 必要なもの

- Windows + Python 3.11+
- ffmpeg (PATH に通っていること)
- Spotify Premium アカウント
- Spotify Developer 登録 (Client ID / Secret)
- LLM 用のサブスクリプション (Maxプラン)
- VOICEVOX 解凍版 (セットアップスクリプトで自動配置)

### Spotify Developer 登録

1. <https://developer.spotify.com/dashboard> でアプリ作成
2. **Redirect URI**: `http://127.0.0.1:11324/auth/spotify/callback`
3. APIs: **Web API** と **Web Playback SDK** をチェック
4. Client ID / Secret をコピー

### セットアップ

```bash
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

# .env に Spotify 認証情報を書く
Copy-Item .env.example .env

# VOICEVOX エンジン (約 1.8GB) を vendor/ に展開
.\scripts\setup_voicevox.ps1

# ジングル素材を ffmpeg で生成
.\scripts\make_jingles.ps1
```

## 使い方

```bash
# VOICEVOX 起動 (別シェル)
.\scripts\run_voicevox.ps1

# サーバ起動
python -m server.main
```

ブラウザで <http://127.0.0.1:11324> を開く → `SPOTIFY ログイン` → `開 始` ボタンで番組スタート。

| 操作 | 動作 |
|---|---|
| 開 始 / 停 止 | 番組のオンエア切替。 停止時は 880 Hz × 3 |
| お便り | フォームから投函。 Spotify URL を貼ると次曲をリクエスト |
| 設定 | ジャンル / 推しアーティスト / 言語 / 曲振り頻度 等 |
| JA / EN | UI 言語切替 (DJ の喋りは日本語のまま) |

## テスト

```bash
.\.venv\Scripts\python.exe -m pytest tests/ -v          # 単体 77 件
.\.venv\Scripts\python.exe tests\integration_stress.py 8  # 負荷
```

詳細は [`tests/TESTLOG.md`](tests/TESTLOG.md) / [`tests/CHECKLIST.md`](tests/CHECKLIST.md)。

## ライセンス

[MIT License](LICENSE) © 2026 cUDGk
