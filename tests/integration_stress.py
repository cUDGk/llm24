"""ON AIR にして /api/next-segment を10連発で叩き、各種計測を実証する。

実行: .venv\\Scripts\\python.exe tests\\integration_stress.py
"""

from __future__ import annotations

import asyncio
import statistics
import sys
import time

import httpx

# Windows PowerShell cp932 出力対策: UTF-8 で stdout 出力
sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

BASE = "http://127.0.0.1:11324"


async def main(n: int = 10) -> int:
    async with httpx.AsyncClient(base_url=BASE, timeout=120.0) as c:
        # 確実に on_air リセット
        try:
            await c.post("/api/offair")
        except Exception:
            pass
        # 直近の TTS キャッシュをそのまま使うため設定そのまま
        r = await c.post("/api/onair")
        if r.status_code != 200:
            print(f"FAIL onair {r.status_code} {r.text}")
            return 1
        print(f"[onair] {r.json()}")

        kinds: dict[str, int] = {}
        durations: list[float] = []
        first_song_seen_at = None
        results: list[dict] = []
        for i in range(n):
            t0 = time.monotonic()
            r = await c.get("/api/next-segment")
            dt = time.monotonic() - t0
            if r.status_code != 200:
                print(f"[{i}] HTTP {r.status_code} {r.text[:200]}")
                continue
            seg = r.json()
            kind = seg.get("kind", "?")
            steps = seg.get("steps") or []
            kinds[kind] = kinds.get(kind, 0) + 1
            durations.append(dt)
            song_step = next((s for s in steps if s.get("type") == "song"), None)
            label = ""
            if song_step:
                if first_song_seen_at is None:
                    first_song_seen_at = i
                label = f"{song_step.get('artist','?')} / {song_step.get('title','?')}"
                if "intro_tts" in song_step:
                    label += " [+intro_tts]"
                else:
                    label += " [no intro]"
            tts_steps = [s for s in steps if s.get("type") == "tts"]
            jingle_steps = [s for s in steps if s.get("type") == "jingle"]
            print(f"[{i}] {dt:6.2f}s kind={kind:13} steps={len(steps)} song={'Y' if song_step else 'N'} tts={len(tts_steps)} jingle={len(jingle_steps)}  {label}")
            results.append({"i": i, "dt": dt, "kind": kind, "song": bool(song_step), "label": label, "has_intro": bool(song_step and song_step.get("intro_tts"))})

        await c.post("/api/offair")

        print()
        print("=== summary ===")
        print(f"kinds: {kinds}")
        if durations:
            print(f"timing: min={min(durations):.2f}s med={statistics.median(durations):.2f}s max={max(durations):.2f}s mean={statistics.mean(durations):.2f}s")
        if first_song_seen_at is not None:
            print(f"first song segment at index: {first_song_seen_at}")
        intro_songs = sum(1 for r in results if r["song"] and r["has_intro"])
        silent_songs = sum(1 for r in results if r["song"] and not r["has_intro"])
        print(f"song segments: {intro_songs} with intro, {silent_songs} silent (intro_every)")
    return 0


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 10
    sys.exit(asyncio.run(main(n)))
