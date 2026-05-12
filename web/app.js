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

for (const lvl of ["log", "warn", "error"]) {
  const orig = console[lvl].bind(console);
  console[lvl] = (...args) => {
    orig(...args);
    _ship(lvl, args);
  };
}
window.addEventListener("error", (e) => _ship("error", [`window.onerror: ${e.message} @ ${e.filename}:${e.lineno}`]));
window.addEventListener("unhandledrejection", (e) => _ship("error", [`unhandledrejection: ${e.reason}`]));

// ----- theme

const UI = {
  theme: localStorage.getItem("llm24_theme") || "dark",
};

function applyTheme() {
  document.documentElement.setAttribute("data-theme", UI.theme);
  $("btn-theme").textContent = UI.theme.toUpperCase();
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

  ST.player.addListener("ready", async ({ device_id }) => {
    ST.deviceId = device_id;
    console.log("[spotify] device ready:", device_id);
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
    alert("Spotify device not ready yet. Wait a moment and press START again.");
    return;
  }
  if (!ST.audioCtx) {
    ST.audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  }
  if (ST.audioCtx.state === "suspended") await ST.audioCtx.resume();

  const r = await fetch("/api/onair", { method: "POST" });
  if (!r.ok) {
    const msg = await r.text();
    alert("ON AIR failed: " + msg);
    return;
  }
  ST.onAir = true;
  ST.ttsAbort = false;
  setIndicator(true);
  $("btn-onair").hidden = true;
  $("btn-offair").hidden = false;
  $("np-state").textContent = "on air";
  loop();
}

async function stopOnAir() {
  ST.onAir = false;
  ST.ttsAbort = true;
  setIndicator(false);
  $("btn-onair").hidden = false;
  $("btn-offair").hidden = true;
  $("np-state").textContent = "stopping";

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
  try {
    while (ST.onAir) {
      try {
        showLoading(true);
        const r = await fetch("/api/next-segment");
        showLoading(false);
        if (r.status === 409) {
          console.warn("[loop] server reports not on-air → stopping client loop");
          ST.onAir = false;
          break;
        }
        if (!r.ok) throw new Error(`${r.status} ${await r.text()}`);
        const seg = await r.json();
        await playSegment(seg);
      } catch (e) {
        showLoading(false);
        console.error("[loop] segment error:", e);
        $("np-state").textContent = "error (retry in 3s)";
        for (let i = 0; i < 15 && ST.onAir; i++) await sleep(200);
      }
    }
  } finally {
    ST.loopRunning = false;
    showLoading(false);
    console.log("[loop] exited");
  }
}

function showLoading(on) {
  const el = $("loading");
  if (!el) return;
  if (on) el.classList.add("show");
  else el.classList.remove("show");
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
  $("np-state").textContent = "playing";
  const img = $("np-art");
  if (step.album_image) {
    img.onload = () => img.classList.add("show");
    img.onerror = () => {
      img.classList.remove("show");
      console.warn("[ui] album image failed to load:", step.album_image);
    };
    img.src = step.album_image;
  } else {
    img.classList.remove("show");
    img.removeAttribute("src");
    console.log("[ui] no album_image in step");
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
    $("m-status").textContent = "sent";
    $("m-body").value = "";
    $("m-request").value = "";
    $("m-force").checked = false;
    setTimeout(() => ($("m-status").textContent = ""), 3000);
  } else {
    $("m-status").textContent = "failed: " + (await r.text());
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
  $("s-status").textContent = r.ok ? "saved" : "failed";
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

$("btn-theme").addEventListener("click", () => {
  UI.theme = UI.theme === "dark" ? "light" : "dark";
  localStorage.setItem("llm24_theme", UI.theme);
  applyTheme();
});

// ----- init

(async () => {
  applyTheme();
  const r = await fetch("/api/status");
  const j = await r.json();
  if (!j.spotify_authenticated) {
    $("btn-spotify-login").hidden = false;
    $("btn-onair").hidden = true;
  }
  await loadSettings();
  await refreshRecent();
})();
