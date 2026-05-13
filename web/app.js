/**
 * LLM24 client.
 *
 * 役割:
 * - Spotify Web Playback SDK 初期化 (Premium 必須、デバイス名 "LLM24")
 * - /api/next-segment を順次取得して再生
 * - TTS は Web Audio API でバッファ再生、曲は Spotify Player
 * - イントロ被せ: TTS再生中は Spotify volume を 0.25 にダッキング
 * - 停止時: フェードアウト + 880Hz サイン波 × 3
 */

const ST = {
  player: null,
  deviceId: null,
  token: null,
  onAir: false,
  audioCtx: null,
  currentTrack: null,
  ttsAbort: false,
};

const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ----- client log forward (so the assistant can read errors from server logs)

function _fmt(args) {
  return args
    .map((a) => {
      if (a instanceof Error) return `${a.name}: ${a.message}`;
      if (typeof a === "string") return a;
      try { return JSON.stringify(a); } catch { return String(a); }
    })
    .join(" ");
}

function _ship(level, args) {
  const msg = _fmt(args).slice(0, 4000);
  try {
    fetch("/api/clientlog", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ level, msg }),
      keepalive: true,
    }).catch(() => {});
  } catch {}
}

// サーバには warn / error だけ転送 (info ログは負荷になるのでブラウザ内のみ)
for (const lvl of ["warn", "error"]) {
  const orig = console[lvl].bind(console);
  console[lvl] = (...args) => {
    orig(...args);
    _ship(lvl, args);
  };
}
window.addEventListener("error", (e) => _ship("error", [`window.onerror: ${e.message} @ ${e.filename}:${e.lineno}`]));
window.addEventListener("unhandledrejection", (e) => _ship("error", [`unhandledrejection: ${e.reason}`]));

// ----- i18n (テーマはダーク固定で切替なし)

const UI = {
  lang: localStorage.getItem("llm24_lang") || "ja",
};

const I18N = {
  ja: {
    onair_off: "オンエア",
    start: "開 始", stop: "停 止", spotify_login: "SPOTIFY ログイン",
    now_playing: "再生中", off_air: "— オフエア —",
    now_loading: "読み込み中",
    state_idle: "停止中", state_on_air: "オンエア中", state_playing: "再生中",
    state_stopping: "停止しています", state_error: "エラー (3秒後に再試行)",
    next_track: "次の曲",
    mail: "お便り", radio_name: "ラジオネーム", body: "本文",
    track_url: "Spotifyの曲・プレイリストURL (任意)", force_next: "次の曲で必ず反映する",
    submit: "投 函", submit_ok: "投函しました", submit_fail: "失敗",
    bad_url: "Spotifyの曲またはプレイリストURLを入力してください",
    sent_mails: "投函済み",
    tag_queued: "未読", tag_read: "読了", tag_consumed: "消化",
    recent: "最近の曲", settings: "設定", open_settings: "設定を開く",
    genres: "ジャンル (カンマ区切り)",
    seed_artists: "推しアーティスト (カンマ区切り、空でジャンル選曲のみ)",
    excl_artists: "除外アーティスト (カンマ区切り)",
    personality: "性格カスタム", chat_freq: "雑談頻度",
    freq_loose: "緩い", freq_normal: "普通", freq_dense: "多め",
    mail_adoption: "お便り採用率",
    adopt_every: "毎回", adopt_few: "数曲に1回", adopt_full: "溜まったら",
    jingle_on: "時報ジングル ON", save: "保 存", save_ok: "保存しました",
    spotify_not_ready: "Spotifyデバイス未準備。少し待って再度押してください。",
    onair_failed: "オンエア開始失敗: ",
    premium_required: "Premium未加入: 再生不可",
  },
  en: {
    onair_off: "ON AIR",
    theme_dark: "DARK", theme_light: "LIGHT",
    start: "START", stop: "STOP", spotify_login: "SPOTIFY LOGIN",
    now_playing: "NOW PLAYING", off_air: "— OFF AIR —",
    now_loading: "NOW LOADING",
    state_idle: "idle", state_on_air: "on air", state_playing: "playing",
    state_stopping: "stopping", state_error: "error (retry in 3s)",
    next_track: "NEXT",
    mail: "MAIL", radio_name: "Radio Name", body: "Message",
    track_url: "Spotify track / playlist URL (optional)", force_next: "Apply to the very next track",
    submit: "SEND", submit_ok: "sent", submit_fail: "failed",
    bad_url: "Must be a Spotify track or playlist URL",
    sent_mails: "SENT MAILS",
    tag_queued: "QUEUED", tag_read: "READ", tag_consumed: "READ",
    recent: "RECENT", settings: "SETTINGS", open_settings: "Open settings",
    genres: "Genres (comma-separated)",
    seed_artists: "Seed artists (comma-separated, empty = genre only)",
    excl_artists: "Excluded artists (comma-separated)",
    personality: "Personality custom", chat_freq: "Chat frequency",
    freq_loose: "loose", freq_normal: "normal", freq_dense: "dense",
    mail_adoption: "Mail adoption rate",
    adopt_every: "every track", adopt_few: "every few tracks", adopt_full: "when queue is full",
    jingle_on: "Time-signal jingle ON", save: "SAVE", save_ok: "saved",
    spotify_not_ready: "Spotify device not ready yet. Wait a moment and press START again.",
    onair_failed: "ON AIR failed: ",
    premium_required: "Premium required: playback unavailable",
  },
};

function t(key) {
  return (I18N[UI.lang] || I18N.ja)[key] ?? key;
}

function applyI18n() {
  const dict = I18N[UI.lang] || I18N.ja;
  for (const el of document.querySelectorAll("[data-i18n]")) {
    const key = el.getAttribute("data-i18n");
    if (dict[key] != null) el.textContent = dict[key];
  }
  document.documentElement.lang = UI.lang;
  const lb = $("btn-lang");
  if (lb) lb.textContent = UI.lang.toUpperCase();
}

// ----- token

async function fetchToken() {
  const r = await fetch("/api/spotify/token");
  if (r.status === 401) {
    $("btn-spotify-login").hidden = false;
    $("btn-toggle").hidden = true;
    return null;
  }
  // 成功 = 認証済みなのでログインボタンを必ず隠す
  $("btn-spotify-login").hidden = true;
  $("btn-toggle").hidden = false;
  const j = await r.json();
  return j.access_token;
}

// ----- Spotify SDK

window.onSpotifyWebPlaybackSDKReady = async () => {
  await initSpotifyPlayer();
};

async function initSpotifyPlayer() {
  if (ST.player) return;  // 既に初期化済み
  ST.token = await fetchToken();
  if (!ST.token) return;

  ST.player = new Spotify.Player({
    name: "LLM24",
    getOAuthToken: (cb) => fetchToken().then((t) => { ST.token = t; cb(t); }),
    volume: 1.0,
  });

  ST.player.addListener("ready", async ({ device_id }) => {
    ST.deviceId = device_id;
    console.log("[spotify] device ready:", device_id);
    $("btn-spotify-login").hidden = true;
    $("btn-toggle").hidden = false;
    // autoplay policy 対策: 早めに HTMLMediaElement をアクティブ化しておく
    try {
      if (typeof ST.player.activateElement === "function") {
        await ST.player.activateElement();
      }
    } catch {}
    try {
      await fetch("/api/spotify/device", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ device_id }),
      });
    } catch (e) {
      console.error("[spotify] failed to register device on server", e);
    }
  });

  ST.player.addListener("not_ready", ({ device_id }) => {
    console.warn("[spotify] device offline:", device_id);
  });

  ST.player.addListener("initialization_error", (e) => console.error("init", e));
  ST.player.addListener("authentication_error", (e) => console.error("auth", e));
  ST.player.addListener("account_error", (e) => console.error("account (Premium必須)", e));
  ST.player.addListener("playback_error", (e) => console.error("playback", e));

  ST.player.addListener("player_state_changed", (s) => {
    if (!s) return;
    // 必要に応じて current state を UI へ反映
  });

  await ST.player.connect();
}

async function transferPlayback(deviceId, play = false) {
  const tok = await fetchToken();
  if (!tok) return;
  const r = await fetch("https://api.spotify.com/v1/me/player", {
    method: "PUT",
    headers: {
      Authorization: `Bearer ${tok}`,
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ device_ids: [deviceId], play }),
  });
  if (!r.ok && r.status !== 204) {
    console.warn("[spotify] transfer:", r.status, await r.text());
  }
}

// ----- on/off air loop

async function startOnAir() {
  if (ST.onAir || ST.loopRunning) {
    console.warn("[start] already on-air");
    return;
  }
  // 完全停止後の再開: SDK が外れていれば再接続する
  if (!ST.player) {
    await initSpotifyPlayer();
    // ready イベント待ち (最大5秒)
    for (let i = 0; i < 25 && !ST.deviceId; i++) await sleep(200);
  }
  if (!ST.deviceId) {
    alert(t("spotify_not_ready"));
    return;
  }
  // activateElement (autoplay policy 対策、user-gesture内で実行)
  try {
    if (typeof ST.player.activateElement === "function") {
      await ST.player.activateElement();
    }
  } catch {}
  if (!ST.audioCtx) {
    ST.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (ST.audioCtx.state === "suspended") await ST.audioCtx.resume();

  const r = await fetch("/api/onair", { method: "POST" });
  if (!r.ok) {
    const msg = await r.text();
    alert(t("onair_failed") + msg);
    return;
  }
  ST.onAir = true;
  ST.ttsAbort = false;
  setOnAirUI(true);
  $("np-state").textContent = t("state_on_air");
  loop();
}

async function stopOnAir() {
  ST.onAir = false;
  ST.ttsAbort = true;
  setOnAirUI(false);
  $("np-state").textContent = t("state_stopping");

  if (ST.player) {
    // sine S字で 1.4秒かけてフェードアウト
    await rampVolume(1.0, 0, 1400, 28);
    try { await ST.player.pause(); } catch {}
    try { await ST.player.disconnect(); } catch {}
    ST.player = null;
    ST.deviceId = null;
  }

  await playStopChime();
  await fetch("/api/offair", { method: "POST" });
  $("np-state").textContent = "idle";
  $("np-title").textContent = "—";
  $("np-artist").textContent = "—";
  $("np-art").classList.remove("show");
}

async function loop() {
  if (ST.loopRunning) {
    console.warn("[loop] already running, skip duplicate start");
    return;
  }
  ST.loopRunning = true;
  ST.nextSegmentPromise = null;
  try {
    while (ST.onAir) {
      try {
        // 既にプリフェッチ済みなら即取得、なければここで fetch
        if (!ST.nextSegmentPromise) {
          showLoading(true);
          ST.nextSegmentPromise = fetchNextSegment();
        }
        const seg = await ST.nextSegmentPromise;
        ST.nextSegmentPromise = null;
        showLoading(false);

        if (seg === "stopped") {
          ST.onAir = false;
          break;
        }
        if (!seg) {
          throw new Error("segment fetch failed");
        }

        // 曲が含まれるセグメントなら、再生中に次の segment を先取りする
        const hasSong = (seg.steps || []).some((s) => s && s.type === "song");
        if (hasSong) {
          setTimeout(async () => {
            if (ST.onAir && !ST.nextSegmentPromise) {
              ST.nextSegmentPromise = fetchNextSegment();
              // プリフェッチが返ったら次曲プレビュー表示
              const nextSeg = await ST.nextSegmentPromise;
              if (nextSeg && nextSeg !== "stopped") showNextUp(nextSeg);
            }
          }, 15000);
        }

        clearNextUp();
        await playSegment(seg);
      } catch (e) {
        showLoading(false);
        ST.nextSegmentPromise = null;
        console.error("[loop] segment error:", e);
        $("np-state").textContent = t("state_error");
        for (let i = 0; i < 15 && ST.onAir; i++) await sleep(200);
      }
    }
  } finally {
    ST.loopRunning = false;
    ST.nextSegmentPromise = null;
    showLoading(false);
    console.log("[loop] exited");
  }
}

async function fetchNextSegment() {
  try {
    const r = await fetch("/api/next-segment");
    if (r.status === 409) {
      console.warn("[loop] server says not on-air");
      return "stopped";
    }
    if (!r.ok) {
      console.warn("[loop] next-segment HTTP", r.status, await r.text());
      return null;
    }
    return await r.json();
  } catch (e) {
    console.warn("[loop] fetchNextSegment threw", e);
    return null;
  }
}

function setAlbumArt(url) {
  const img = $("np-art");
  // 一旦リセット (同じ src を再設定しても load イベントが発火しないため)
  img.classList.remove("show");
  img.onload = null;
  img.onerror = null;
  img.removeAttribute("src");

  if (!url) return;

  img.onload = () => img.classList.add("show");
  img.onerror = () => {
    img.classList.remove("show");
    console.warn("[ui] album image failed to load:", url);
  };
  // src 設定で load 開始
  img.src = url;
  // 既にブラウザキャッシュにあれば complete が即 true、onload を待たずに show を付ける
  if (img.complete && img.naturalWidth > 0) {
    img.classList.add("show");
  }
}

function showLoading(on) {
  const el = $("loading");
  if (!el) return;
  if (on) el.classList.add("show");
  else el.classList.remove("show");
}

function showNextUp(seg) {
  const song = (seg.steps || []).find((s) => s && s.type === "song");
  const box = $("next-up");
  if (!song) { box.hidden = true; return; }
  $("next-title").textContent = song.title || "";
  $("next-artist").textContent = song.artist ? "/ " + song.artist : "";
  box.hidden = false;
}

function clearNextUp() {
  const box = $("next-up");
  if (!box) return;
  box.hidden = true;
  $("next-title").textContent = "";
  $("next-artist").textContent = "";
}

// ----- segment playback

async function playSegment(seg) {
  for (const step of seg.steps || []) {
    if (!step) continue;
    if (!ST.onAir) return;
    if (step.type === "jingle") {
      await playSampleUrl(step.url, { duck: false, text: "" });
    } else if (step.type === "tts") {
      await playSampleUrl(step.url, {
        duck: step.ducking === "intro",
        text: step.text || "",
      });
    } else if (step.type === "song") {
      await playSong(step);
    }
  }
}

async function playSampleUrl(url, { duck = false, text = "" } = {}) {
  const buf = await fetchAudioBuffer(url);
  if (duck && ST.player) {
    await rampVolume(1.0, 0.25, 250);
  }
  if (text) showSubtitle(text);
  await playBuffer(buf);
  hideSubtitle();
  if (duck && ST.player) {
    await rampVolume(0.25, 1.0, 800);
  }
}

/** Spotify Player の音量を from → to へ sine ease-in-out で滑らかに変化させる。
 *  ease 関数: y = 0.5 - 0.5*cos(π * t)  → 始端と終端が緩やかなS字。
 */
async function rampVolume(from, to, durationMs, steps = 24) {
  if (!ST.player) return;
  const stepMs = Math.max(8, durationMs / steps);
  for (let i = 1; i <= steps; i++) {
    const t = i / steps;
    const eased = 0.5 - 0.5 * Math.cos(Math.PI * t);
    const v = from + (to - from) * eased;
    try { await ST.player.setVolume(Math.max(0, Math.min(1, v))); } catch {}
    await sleep(stepMs);
  }
}

function showSubtitle(text) {
  const el = $("subtitle");
  el.textContent = text;
  // 一度フェードアウト → テキスト差し替え → フェードイン
  requestAnimationFrame(() => el.classList.add("show"));
}

function hideSubtitle() {
  $("subtitle").classList.remove("show");
}

async function fetchAudioBuffer(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`fetch ${url} failed: ${r.status}`);
  const arr = await r.arrayBuffer();
  return await ST.audioCtx.decodeAudioData(arr);
}

function playBuffer(buf) {
  return new Promise((resolve) => {
    const src = ST.audioCtx.createBufferSource();
    src.buffer = buf;
    src.connect(ST.audioCtx.destination);
    src.onended = () => resolve();
    src.start();
    // 強制停止対応
    const checkAbort = () => {
      if (ST.ttsAbort) {
        try { src.stop(); } catch {}
        resolve();
      } else if (ST.onAir) {
        setTimeout(checkAbort, 200);
      } else {
        try { src.stop(); } catch {}
        resolve();
      }
    };
    setTimeout(checkAbort, 200);
  });
}

async function playSong(step) {
  ST.currentTrack = step;
  $("np-title").textContent = step.title;
  $("np-artist").textContent = step.artist;
  $("np-state").textContent = "playing";
  setAlbumArt(step.album_image);
  refreshRecent();

  const ok = await startSpotifyPlay(step.spotify_uri);
  if (!ok) {
    console.error("[spotify] could not play song; skipping to next");
    $("np-state").textContent = "spotify error";
    await sleep(2000);
    return;
  }

  // 曲開始と同時にイントロ被せ (ダッキング、sineで自然に)
  if (step.intro_tts) {
    await sleep(300);
    await rampVolume(1.0, 0.25, 250);
    showSubtitle(step.intro_tts.text);
    try {
      const buf = await fetchAudioBuffer(step.intro_tts.url);
      await playBuffer(buf);
    } catch (e) {
      console.warn("[tts] intro playback failed", e);
    }
    hideSubtitle();
    // サイン波 ease-in-out で 800ms かけてフェードイン
    await rampVolume(0.25, 1.0, 800);
  }

  await waitSongEnd(step.duration_ms);
}

async function startSpotifyPlay(uri) {
  if (!ST.deviceId) {
    console.warn("[spotify] no device_id yet");
    return false;
  }
  const r = await fetch("/api/spotify/play", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ uri }),
  });
  if (r.ok) return true;
  const body = await r.text();
  console.warn(`[spotify] /api/spotify/play → ${r.status} ${body}`);
  return false;
}

/** 曲の終了を待つ。3つの終了条件で確実に抜ける:
 *   (1) Spotify state.position が duration-500ms 以上 (= 曲終端)
 *   (2) Spotify state.position が一度動いた後、長時間 paused + position=0 (= SDK が曲を自動停止)
 *   (3) 壁時計で (knownDuration + 3000ms) 超過 (= SDK が応答しない場合のセーフティ)
 *   (4) 絶対上限 8分 (= duration=0 のリクエスト曲フォールバック)
 */
function waitSongEnd(initialDurationMs) {
  return new Promise(async (resolve) => {
    const wallStart = Date.now();
    let knownDuration = initialDurationMs || 0;
    let positionEverMoved = false;
    let lastPausedZeroAt = 0;

    const finish = () => { updateProgress(0, 0); resolve(); };

    while (ST.onAir) {
      const elapsed = Date.now() - wallStart;
      let state = null;
      try { state = await ST.player.getCurrentState(); } catch {}

      if (state && typeof state.duration === "number" && state.duration > 0) {
        knownDuration = state.duration;
        updateProgress(state.position, state.duration);
        if (state.position > 1000) positionEverMoved = true;

        // (1) 終端到達
        if (state.position >= state.duration - 500) return finish();

        // (2) 一度動いた後の paused + position=0 が 2.5秒続いたら次曲扱い
        if (positionEverMoved && state.paused && state.position === 0) {
          if (!lastPausedZeroAt) lastPausedZeroAt = Date.now();
          else if (Date.now() - lastPausedZeroAt > 2500) return finish();
        } else {
          lastPausedZeroAt = 0;
        }
      } else {
        updateProgress(elapsed, knownDuration);
      }

      // (3) 壁時計でduration超過
      if (knownDuration > 0 && elapsed > knownDuration + 3000) return finish();
      // (4) 絶対上限
      if (elapsed > 8 * 60 * 1000) return finish();

      await sleep(500);
    }
    finish();
  });
}

function updateProgress(positionMs, durationMs) {
  const bar = $("progress-bar");
  const txt = $("progress-text");
  if (!bar || !txt) return;
  if (!durationMs || durationMs <= 0) {
    bar.style.width = "0%";
    txt.textContent = "";
    return;
  }
  const pct = Math.max(0, Math.min(100, (positionMs / durationMs) * 100));
  bar.style.width = pct.toFixed(1) + "%";
  txt.textContent = `${fmtMs(positionMs)} / ${fmtMs(durationMs)}  −${fmtMs(durationMs - positionMs)}`;
}

function fmtMs(ms) {
  if (!ms || ms < 0) return "0:00";
  const s = Math.floor(ms / 1000);
  const m = Math.floor(s / 60);
  const r = s % 60;
  return `${m}:${r.toString().padStart(2, "0")}`;
}

// ----- stop chime: 880Hz × 3

async function playStopChime() {
  const ctx = ST.audioCtx || new (window.AudioContext || window.webkitAudioContext)();
  if (ctx.state === "suspended") await ctx.resume();
  const now = ctx.currentTime;
  const beeps = [
    { start: 0.0, dur: 0.2 },
    { start: 0.4, dur: 0.2 },
    { start: 0.8, dur: 0.6 },
  ];
  for (const b of beeps) {
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = "sine";
    o.frequency.value = 880;
    g.gain.setValueAtTime(0.0, now + b.start);
    g.gain.linearRampToValueAtTime(0.35, now + b.start + 0.01);
    g.gain.setValueAtTime(0.35, now + b.start + b.dur - 0.02);
    g.gain.linearRampToValueAtTime(0.0, now + b.start + b.dur);
    o.connect(g);
    g.connect(ctx.destination);
    o.start(now + b.start);
    o.stop(now + b.start + b.dur);
  }
  await sleep(1500);
}

// ----- UI: indicator + toggle button

function setIndicator(on) {
  const el = $("onair-indicator");
  if (on) {
    el.classList.add("on");
    el.classList.remove("off");
  } else {
    el.classList.add("off");
    el.classList.remove("on");
  }
}

function setOnAirUI(on) {
  setIndicator(on);
  const btn = $("btn-toggle");
  btn.textContent = on ? t("stop") : t("start");
  btn.setAttribute("data-i18n", on ? "stop" : "start");
  if (on) btn.classList.add("active");
  else btn.classList.remove("active");
}

// ----- mail form

$("mail-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const reqRaw = $("m-request").value.trim();
  // バリデーション: 入力があれば Spotify track or playlist URL でなければ拒否
  if (reqRaw && !/(?:track|playlist)[:/][A-Za-z0-9]{22}/.test(reqRaw)) {
    $("m-status").textContent = t("bad_url");
    return;
  }
  const payload = {
    radio_name: $("m-name").value.trim(),
    body: $("m-body").value.trim(),
    request: reqRaw || null,
    force: $("m-force").checked,
  };
  const r = await fetch("/api/mail", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (r.ok) {
    $("m-status").textContent = t("submit_ok");
    $("m-body").value = "";
    $("m-request").value = "";
    $("m-force").checked = false;
    refreshMails();
    setTimeout(() => ($("m-status").textContent = ""), 3000);
  } else {
    $("m-status").textContent = t("submit_fail") + ": " + (await r.text());
  }
});

async function refreshMails() {
  try {
    const r = await fetch("/api/mail?limit=30");
    const rows = await r.json();
    const ul = $("mail-list");
    ul.innerHTML = "";
    for (const m of rows) {
      const li = document.createElement("li");
      if (m.force) li.classList.add("force");
      const tag = m.status === "consumed" ? t("tag_consumed") : m.status === "read" ? t("tag_read") : t("tag_queued");
      const reqHtml = m.request ? `<span class="req">↪ ${escapeHtml(m.request)}</span>` : "";
      li.innerHTML =
        `<span class="name">${escapeHtml(m.radio_name)}` +
        `<span class="tag">${tag}${m.force ? " · FORCE" : ""}</span></span>` +
        `<span class="body">${escapeHtml(m.body)}</span>${reqHtml}`;
      ul.appendChild(li);
    }
  } catch (e) {
    console.warn("[mail] list fetch failed", e);
  }
}

// ----- settings

async function loadSettings() {
  const r = await fetch("/api/settings");
  const s = await r.json();
  $("s-genres").value = (s.genres || []).join(", ");
  $("s-seed-art").value = (s.seed_artists || []).join(", ");
  $("s-excl-art").value = (s.exclude?.artists || []).join(", ");
  $("s-personality").value = s.personality_custom || "";
  $("s-chat-freq").value = s.chat_frequency || "normal";
  $("s-mail-adopt").value = s.mail_adoption || "every_few";
  $("s-jingle").checked = s.jingle_enabled !== false;
}

$("settings-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    genres: $("s-genres").value.split(",").map((x) => x.trim()).filter(Boolean),
    seed_artists: $("s-seed-art").value.split(",").map((x) => x.trim()).filter(Boolean),
    exclude: {
      artists: $("s-excl-art").value.split(",").map((x) => x.trim()).filter(Boolean),
      genres: [],
      keywords: [],
    },
    personality_custom: $("s-personality").value,
    chat_frequency: $("s-chat-freq").value,
    mail_adoption: $("s-mail-adopt").value,
    jingle_enabled: $("s-jingle").checked,
  };
  const r = await fetch("/api/settings", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  $("s-status").textContent = r.ok ? t("save_ok") : t("submit_fail");
  setTimeout(() => ($("s-status").textContent = ""), 3000);
});

// ----- recent

async function refreshRecent() {
  try {
    const r = await fetch("/api/now");
    const j = await r.json();
    const ul = $("recent-list");
    ul.innerHTML = "";
    for (const p of j.recent || []) {
      const li = document.createElement("li");
      li.innerHTML = `<span class="t">${escapeHtml(p.title)}</span><span class="a">${escapeHtml(p.artist)}</span>`;
      ul.appendChild(li);
    }
  } catch (e) {
    console.warn("recent fetch failed", e);
  }
}

function escapeHtml(s) {
  return String(s)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;");
}

// ----- buttons

$("btn-toggle").addEventListener("click", async () => {
  const btn = $("btn-toggle");
  if (btn.disabled) return;
  btn.disabled = true;
  try {
    if (ST.pendingResume) {
      // リロード後の継続再開: サーバ状態は維持されているのでクライアントだけ起こす
      ST.pendingResume = false;
      await resumeOnAir();
    } else if (ST.onAir) {
      await stopOnAir();
    } else {
      await startOnAir();
    }
  } finally {
    btn.disabled = false;
  }
});

async function resumeOnAir() {
  if (!ST.deviceId) {
    alert(t("spotify_not_ready"));
    return;
  }
  if (!ST.audioCtx) ST.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (ST.audioCtx.state === "suspended") await ST.audioCtx.resume();
  ST.onAir = true;
  ST.ttsAbort = false;
  setOnAirUI(true);
  $("np-state").textContent = t("state_on_air");
  loop();
}
$("btn-spotify-login").addEventListener("click", () => {
  window.location.href = "/auth/spotify";
});

$("btn-lang").addEventListener("click", () => {
  UI.lang = UI.lang === "ja" ? "en" : "ja";
  localStorage.setItem("llm24_lang", UI.lang);
  applyI18n();
  // 動的に書いてる要素も再描画
  refreshMails();
  refreshRecent();
  const ind = $("onair-indicator");
  if (ind && !ind.classList.contains("on")) {
    // OFF AIR の表示は indicator の base クラス + on/off で疑似要素なのでテキスト書き換え不要
  }
  if ($("premium-warn") && !$("premium-warn").hidden) {
    $("premium-warn").textContent = t("premium_required");
  }
  if (ST.onAir) $("np-state").textContent = t("state_on_air");
  else $("np-state").textContent = t("state_idle");
  setOnAirUI(ST.onAir);
});

// ----- init

(async () => {
  applyI18n();
  // 初期状態を明示的にリセット (キャッシュやリロード履歴で状態が残らないように)
  $("btn-spotify-login").hidden = true;
  $("btn-toggle").hidden = false;
  $("premium-warn").hidden = true;

  const r = await fetch("/api/status");
  const j = await r.json();

  // サーバが ON AIR 状態のままリロードされた場合は UI を「停止」表示にして、
  // 1クリックで loop 再開できるようにする (AudioContext はユーザー操作前に
  // resume できないので完全自動再開はできない)
  if (j.on_air) {
    setOnAirUI(true);
    $("np-state").textContent = "前回継続中 (▶ で再開)";
    $("btn-toggle").textContent = "▶ 再開";
    ST.pendingResume = true;
  }

  if (!j.spotify_authenticated) {
    $("btn-spotify-login").hidden = false;
    $("btn-toggle").hidden = true;
  } else {
    // Premium チェック
    try {
      const pr = await fetch("/api/spotify/profile");
      if (pr.ok) {
        const pj = await pr.json();
        if (!pj.is_premium) {
          const w = $("premium-warn");
          w.textContent = t("premium_required");
          w.hidden = false;
          console.warn("[spotify] account is not Premium → playback will fail");
        }
      }
    } catch {}
  }
  await loadSettings();
  await refreshRecent();
  await refreshMails();
  setInterval(refreshMails, 30000);
})();
