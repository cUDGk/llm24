# LLM24

24時間稼働する AI DJ ラジオ。台本は Claude Code SDK、TTS は VOICEVOX、再生は Spotify Web Playback SDK。

ローカルで FastAPI を立てて、ブラウザ (Chrome/Edge) で `http://localhost:8000` を開く。

## 必要なもの

- **Windows** + **Python 3.11+**
- **ffmpeg** (PATH に通っていること、または `.env` の `FFMPEG_BIN` で指定)
- **Spotify Premium アカウント** (Web Playback SDK が Premium 必須)
- **Spotify Developer 登録** (Client ID / Secret)
- **Claude Code Max サブスク** (このリポを動かしている Claude Code 環境がそのまま使われる)
- **VOICEVOX** (`scripts/setup_voicevox.ps1` で自動DL/配置)

## セットアップ

### 1. Spotify Developer 登録

1. <https://developer.spotify.com/dashboard> へアクセス
2. 「Create app」
   - App name: `LLM24`（任意）
   - App description: 任意
   - **Redirect URI**: `http://localhost:8000/auth/spotify/callback`
   - APIs: `Web API` と `Web Playback SDK` をチェック
3. 作成後、`Client ID` と `Client secret` をコピー

### 2. `.env` 作成

```powershell
Copy-Item .env.example .env
notepad .env
```

`SPOTIFY_CLIENT_ID` / `SPOTIFY_CLIENT_SECRET` に上で取った値を貼る。

### 3. Python 環境

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

### 4. VOICEVOX 取得

```powershell
.\scripts\setup_voicevox.ps1
```

GitHub Release から CPU 解凍版を落として `vendor/voicevox/` に展開する。約1GB。

### 5. ジングル素材

`scripts/make_jingles.ps1` を実行すると ffmpeg で簡易ジングル (時報/お便り) を生成して `assets/` に置く。
あとでお気に入りのフリー素材に差し替え可能。

```powershell
.\scripts\make_jingles.ps1
```

## 起動

ターミナル2枚を使う。

**VOICEVOX を起動 (1枚目):**
```powershell
.\scripts\run_voicevox.ps1
```

**サーバを起動 (2枚目):**
```powershell
.\.venv\Scripts\Activate.ps1
python -m server.main
```

ブラウザで <http://localhost:8000> を開く → Spotify ログイン → **ON AIR** ボタンで番組開始。

## 仕様

詳細は [`../LLM24_仕様書.md`](../LLM24_仕様書.md) を参照。
