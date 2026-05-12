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

// ----- i18n & theme

const I18N = {
  ja: {
    start: "START", stop: "STOP", spotify_login: "SPOTIFY LOGIN",
    now_playing: "NOW PLAYING", off_air: "— OFF AIR —", state_idle: "idle",
    state_on_air: "on air", state_playing: "playing", state_stopping: "stopping",
    state_error: "error (retry in 3s)",
    mail: "MAIL", radio_name: "ラジオネーム", body: "本文",
    request: "リクエスト (任意)", force_next: "次の曲で必ず反映する",
    submit: "投 函", submit_ok: "投函しました", submit_fail: "失敗",
    recent: "RECENT", settings: "SETTINGS", open_settings: "設定を開く",
    genres: "ジャンル (カンマ区切り)", excl_artists: "除外アーティスト (カンマ区切り)",
    personality: "性格カスタム", chat_freq: "雑談頻度",
    freq_loose: "緩い", freq_normal: "普通", freq_dense: "多め",
    mail_adoption: "お便り採用率",
    adopt_every: "毎回", adopt_few: "数曲に1回", adopt_full: "溜まったら",
    jingle_on: "時報ジングル ON", save: "保 存", save_ok: "保存しました",
  },
  en: {
    start: "START", stop: "STOP", spotify_login: "SPOTIFY LOGIN",
    now_playing: "NOW PLAYING", off_air: "— OFF AIR —", state_idle: "idle",
    state_on_air: "on air", state_playing: "playing", state_stopping: "stopping",
    state_error: "error (retry in 3s)",
    mail: "MAIL", radio_name: "Radio Name", body: "Message",
    request: "Request (optional)", force_next: "Apply to the very next song",
    submit: "SEND", submit_ok: "sent", submit_fail: "failed",
    recent: "RECENT", settings: "SETTINGS", open_settings: "Open settings",
    genres: "Genres (comma-separated)", excl_artists: "Excluded artists (comma-separated)",
    personality: "Personality custom", chat_freq: "Chat frequency",
    freq_loose: "loose", freq_normal: "normal", freq_dense: "dense",
    mail_adoption: "Mail adoption rate",
    adopt_every: "every track", adopt_few: "every few tracks", adopt_full: "when queue is full",
    jingle_on: "Time-signal jingle ON", save: "SAVE", save_ok: "saved",
  },
};

const UI = {
  lang: localStorage.getItem("llm24_lang") || "ja",
  theme: localStorage.getItem("llm24_theme") || "dark",
};

function applyI18n() {
  const dict = I18N[UI.lang] || I18N.ja;
  for (const el of document.querySelectorAll("[data-i18n]")) {
    const key = el.getAttribute("data-i18n");
    if (dict[key] != null) el.textContent = dict[key];
  }
  document.documentElement.lang = UI.lang;
  $("btn-lang").textContent = UI.lang.toUpperCase();
}

function applyTheme() {
  document.documentElement.setAttribute("data-theme", UI.theme);
  $("btn-theme").textContent = UI.theme.toUpperCase();
}

function t(key) {
  return (I18N[UI.lang] || I18N.ja)[key] ?? key;
}

// ----- token

async function fetchToken() {
  const r = await fetch("/api/spotify/token");
  if (r.status === 401) {
    $("btn-spotify-login").hidden = false;
    $("btn-onair").hidden = true;
    return null;
  }
  const j = await r.json();
  return j.access_token;
}

// ----- Spotify SDK

window.onSpotifyWebPlaybackSDKReady = async () => {
  ST.token = await fetchToken();
  if (!ST.token) return;

  ST.player = new Spotify.Player({
    name: "LLM24",
    getOAuthToken: (cb) => fetchToken().then((t) => { ST.token = t; cb(t); }),
    volume: 1.0,
  });

  ST.player.addListener("ready", ({ device_id }) => {
    ST.deviceId = device_id;
    console.log("[spotify] device ready:", device_id);
    transferPlayback(device_id);
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
};

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
  if (!ST.deviceId) {
    alert("Spotifyデバイス未準備。少し待って再度押してください。");
    return;
  }
  if (!ST.audioCtx) {
    ST.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (ST.audioCtx.state === "suspended") await ST.audioCtx.resume();

  const r = await fetch("/api/onair", { method: "POST" });
  if (!r.ok) {
    const msg = await r.text();
    alert("ON AIR失敗: " + msg);
    return;
  }
  ST.onAir = true;
  ST.ttsAbort = false;
  setIndicator(true);
  $("btn-onair").hidden = true;
  $("btn-offair").hidden = false;
  $("np-state").textContent = t("state_on_air");
  loop();
}

async function stopOnAir() {
  ST.onAir = false;
  ST.ttsAbort = true;
  setIndicator(false);
  $("btn-onair").hidden = false;
  $("btn-offair").hidden = true;
  $("np-state").textContent = t("state_stopping");

  if (ST.player) {
    for (let v = 1.0; v >= 0; v -= 0.1) {
      try { await ST.player.setVolume(Math.max(0, v)); } catch {}
      await sleep(120);
    }
    try { await ST.player.pause(); } catch {}
    try { await ST.player.setVolume(1.0); } catch {}
  }

  await playStopChime();
  await fetch("/api/offair", { method: "POST" });
  $("np-state").textContent = t("state_idle");
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
  try {
    while (ST.onAir) {
      try {
        const r = await fetch("/api/next-segment");
        if (r.status === 409) {
          console.warn("[loop] server reports not on-air → stopping client loop");
          ST.onAir = false;
          break;
        }
        if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
        const seg = await r.json();
        await playSegment(seg);
      } catch (e) {
        console.error("[loop] segment error:", e);
        $("np-state").textContent = t("state_error");
        // 3秒、ただしonAir解除されたら即抜ける
        for (let i = 0; i < 15 && ST.onAir; i++) await sleep(200);
      }
    }
  } finally {
    ST.loopRunning = false;
    console.log("[loop] exited");
  }
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
    try { await ST.player.setVolume(0.25); } catch {}
  }
  if (text) showSubtitle(text);
  await playBuffer(buf);
  hideSubtitle();
  if (duck && ST.player) {
    try { await ST.player.setVolume(1.0); } catch {}
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
  $("np-state").textContent = t("state_playing");
  if (step.album_image) {
    $("np-art").src = step.album_image;
    $("np-art").classList.add("show");
  } else {
    $("np-art").classList.remove("show");
  }
  refreshRecent();

  const ok = await startSpotifyPlay(step.spotify_uri);
  if (!ok) {
    console.error("[spotify] could not play song; skipping to next");
    $("np-state").textContent = "spotify error";
    await sleep(2000);
    return;
  }

  await waitSongEnd(step.duration_ms);
}

async function startSpotifyPlay(uri) {
  if (!ST.deviceId) {
    console.warn("[spotify] no device_id yet");
    return false;
  }
  for (let attempt = 0; attempt < 2; attempt++) {
    const tok = await fetchToken();
    if (!tok) return false;
    if (attempt > 0) {
      // 2回目: デバイス転送して再生強制
      await transferPlayback(ST.deviceId, false);
      await sleep(400);
    }
    const r = await fetch(
      `https://api.spotify.com/v1/me/player/play?device_id=${ST.deviceId}`,
      {
        method: "PUT",
        headers: {
          Authorization: `Bearer ${tok}`,
          "Content-Type": "application/json",
        },
        body: JSON.stringify({ uris: [uri] }),
      }
    );
    if (r.ok || r.status === 204) return true;
    const body = await r.text();
    console.warn(`[spotify] play try${attempt + 1} → ${r.status} ${body}`);
    if (r.status === 404 || r.status === 403 || r.status === 401) {
      // 404=device not found / 403=Premium必要 or scope不足 / 401=token切れ
      // 次のループでtransfer+再取得
      continue;
    }
    return false;
  }
  return false;
}

function waitSongEnd(durationMs) {
  return new Promise((resolve) => {
    const start = Date.now();
    const tick = () => {
      if (!ST.onAir) { resolve(); return; }
      const elapsed = Date.now() - start;
      if (elapsed >= durationMs - 300) { resolve(); return; }
      setTimeout(tick, 400);
    };
    tick();
  });
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

// ----- UI: indicator

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

// ----- mail form

$("mail-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const payload = {
    radio_name: $("m-name").value.trim(),
    body: $("m-body").value.trim(),
    request: $("m-request").value.trim() || null,
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
    setTimeout(() => ($("m-status").textContent = ""), 3000);
  } else {
    $("m-status").textContent = t("submit_fail") + ": " + (await r.text());
  }
});

// ----- settings

async function loadSettings() {
  const r = await fetch("/api/settings");
  const s = await r.json();
  $("s-genres").value = (s.genres || []).join(", ");
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

$("btn-onair").addEventListener("click", startOnAir);
$("btn-offair").addEventListener("click", stopOnAir);
$("btn-spotify-login").addEventListener("click", () => {
  window.location.href = "/auth/spotify";
});

$("btn-lang").addEventListener("click", () => {
  UI.lang = UI.lang === "ja" ? "en" : "ja";
  localStorage.setItem("llm24_lang", UI.lang);
  applyI18n();
});

$("btn-theme").addEventListener("click", () => {
  UI.theme = UI.theme === "dark" ? "light" : "dark";
  localStorage.setItem("llm24_theme", UI.theme);
  applyTheme();
});

// ----- init

(async () => {
  applyTheme();
  applyI18n();
  const r = await fetch("/api/status");
  const j = await r.json();
  if (!j.spotify_authenticated) {
    $("btn-spotify-login").hidden = false;
    $("btn-onair").hidden = true;
  }
  await loadSettings();
  await refreshRecent();
})();
