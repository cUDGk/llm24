"""VOICEVOX Engine (Windows CPU) を GitHub Release から取得して vendor/voicevox/ に展開する。

実行:
    .venv\\Scripts\\python scripts\\setup_voicevox.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

try:
    import py7zr
except ImportError:
    print("py7zr が入っていません。先に `pip install -r requirements.txt` してください。")
    sys.exit(1)


ROOT = Path(__file__).resolve().parent.parent
VENDOR = ROOT / "vendor"
TARGET = VENDOR / "voicevox"
ARCHIVE = VENDOR / "voicevox_engine.7z"

ASSET_PREFIX = "voicevox_engine-windows-cpu-"
ASSET_SUFFIX = ".7z.001"
API_URL = "https://api.github.com/repos/VOICEVOX/voicevox_engine/releases/latest"


def fetch_release_info() -> dict:
    req = urllib.request.Request(API_URL, headers={"User-Agent": "LLM24-setup"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def pick_asset(info: dict) -> dict:
    for asset in info["assets"]:
        name = asset["name"]
        if name.startswith(ASSET_PREFIX) and name.endswith(ASSET_SUFFIX):
            return asset
    raise RuntimeError(f"Windows CPU 用アセットが見つかりません: prefix={ASSET_PREFIX}")


def download(url: str, dest: Path, expected_size: int) -> None:
    if dest.exists() and dest.stat().st_size == expected_size:
        print(f"[skip] 既にDL済み: {dest.name} ({expected_size:,} bytes)")
        return

    print(f"[download] {url}")
    print(f"           -> {dest}")
    req = urllib.request.Request(url, headers={"User-Agent": "LLM24-setup"})
    with urllib.request.urlopen(req, timeout=60) as resp, open(dest, "wb") as f:
        total = expected_size or int(resp.headers.get("Content-Length", "0") or 0)
        read = 0
        chunk = 1024 * 256
        last_pct = -1
        while True:
            buf = resp.read(chunk)
            if not buf:
                break
            f.write(buf)
            read += len(buf)
            if total:
                pct = int(read * 100 / total)
                if pct != last_pct and pct % 5 == 0:
                    print(f"  {pct:3d}%  {read:>13,} / {total:,}")
                    last_pct = pct
    print(f"[done] {dest.stat().st_size:,} bytes")


def extract(archive: Path, target: Path) -> None:
    if target.exists() and any(target.iterdir()):
        print(f"[skip] 既に展開済み: {target}")
        return
    target.mkdir(parents=True, exist_ok=True)
    print(f"[extract] {archive} -> {target}")
    with py7zr.SevenZipFile(archive, mode="r") as z:
        z.extractall(path=target)
    print("[done] extract")


def find_engine_exe(target: Path) -> Path | None:
    for p in target.rglob("run.exe"):
        return p
    for p in target.rglob("voicevox_engine.exe"):
        return p
    return None


def main() -> int:
    VENDOR.mkdir(parents=True, exist_ok=True)
    print("[info] VOICEVOX Engine の最新リリース情報を取得中...")
    info = fetch_release_info()
    print(f"[info] tag={info['tag_name']}  name={info['name']}")

    asset = pick_asset(info)
    print(f"[info] asset={asset['name']}  size={asset['size']:,} bytes")

    download(asset["browser_download_url"], ARCHIVE, asset["size"])
    extract(ARCHIVE, TARGET)

    exe = find_engine_exe(TARGET)
    if exe is None:
        print("[warn] run.exe が見つかりませんでした。vendor/voicevox/ の中身を確認してください。")
        return 1
    print(f"[ok] VOICEVOX engine 実行ファイル: {exe}")
    print(f"[ok] 起動コマンド例:")
    print(f'      & "{exe}"')
    return 0


if __name__ == "__main__":
    sys.exit(main())
