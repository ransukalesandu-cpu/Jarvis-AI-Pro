// JARVIS web client: connection, state, display. Audio lives in audio.js.
// No keys and no assistant logic here — the hub does all of that.
import { THEME } from "./theme.js";
import { Governor } from "./governor.js";
import { Orb } from "./orb.js";

const $ = (id) => document.getElementById(id);
const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch { /* private mode */ } },
};

const STATE_LABELS = {
  disconnected: "Connecting…", idle: "Tap to talk", listening: "Listening",
  thinking: "Thinking", speaking: "Speaking", error: "Error",
};
// Hub (Phase 1 UI) states -> client states.
const HUB_STATES = { LISTENING: "idle", THINKING: "thinking", SPEAKING: "speaking",
  SLEEPING: "idle", INITIALIZING: "thinking", LOCKED: "error", ERROR: "error" };

class App {
  constructor() {
    this.device = store.get("jarvis.device", "");
    this.ws = null;
    this.backoff = 500;
    this.state = "disconnected";
    this.active = null;          // which device owns the microphone
    this.listening = false;      // this device is streaming its mic
    this.conversation = store.get("jarvis.conversation", "0") === "1";
    this.audio = null;           // audio.js module, once loaded
    const quality = store.get("jarvis.quality", "auto");
    this.governor = new Governor(THEME, {
      initialTier: store.get("jarvis.tier", Governor.initialTierFor(navigator)),
      override: quality === "auto" ? null : quality,
      onChange: (tier) => { store.set("jarvis.tier", tier); this.orb.resize(); },
    });
    this.orb = new Orb($("orb"), this.governor);
    this.bind();
    this.orb.start();
    this.connect();
    this.loadAudio();
    this.keepAwake();
    if ("serviceWorker" in navigator) navigator.serviceWorker.register("/sw.js").catch(() => {});
  }

  // ── wiring ────────────────────────────────────────────────────────────────
  bind() {
    $("orb").addEventListener("click", () => this.toggleListening());
    $("stop").addEventListener("click", () => this.stop());
    const conv = $("conversation");
    conv.checked = this.conversation;
    conv.addEventListener("change", () => {
      this.conversation = conv.checked;
      store.set("jarvis.conversation", this.conversation ? "1" : "0");
      this.send({ type: "conversation_mode", on: this.conversation });
    });
    $("text-form").addEventListener("submit", (e) => {
      e.preventDefault();
      const text = $("text").value.trim();
      if (!text) return;
      this.send({ type: "activate" });
      this.send({ type: "text", text });
      $("text").value = "";
    });
    $("settings-btn").addEventListener("click", () => $("settings").showModal());
    const q = $("quality");
    q.value = store.get("jarvis.quality", "auto");
    q.addEventListener("change", () => { store.set("jarvis.quality", q.value); this.governor.setOverride(q.value); });
    const fps = $("show-fps");
    setInterval(() => {
      if (fps.checked) $("fps").textContent =
        `${(this.governor.lastFps || 0).toFixed(0)} fps · ${(this.governor.lastRenderMs || 0).toFixed(1)} ms · tier ${this.governor.tier}`;
    }, 1000);
    $("viewer-close").addEventListener("click", () => this.closeViewer());
    document.addEventListener("visibilitychange", () => { if (!document.hidden) this.keepAwake(); });
  }

  async loadAudio() {
    try {
      const mod = await import("./audio.js");
      let lastReport = 0;
      this.audio = new mod.AudioLink({
        onMicFrame: (pcm) => this.sendBinary(pcm),
        onLevel: (v) => this.orb.setLevel(v),
        onBuffered: (ms) => {          // lets the hub know when speech really ended
          const now = performance.now();
          if (now - lastReport > 250) { lastReport = now; this.send({ type: "playback", buffered_ms: Math.round(ms) }); }
        },
      });
    } catch (err) {
      console.warn("Audio unavailable", err);
    }
  }

  async keepAwake() {
    try {
      if ("wakeLock" in navigator && !document.hidden) {
        this.wakeLock = await navigator.wakeLock.request("screen");
      }
    } catch { /* not allowed now; retried on the next visibility change */ }
  }

  // ── connection ────────────────────────────────────────────────────────────
  connect() {
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/ws/client`);
    ws.binaryType = "arraybuffer";
    this.ws = ws;
    ws.onopen = () => {
      ws.send(JSON.stringify({ type: "hello", token: store.get("jarvis.token", ""),
        device: this.device, ua: navigator.userAgent, tier: this.governor.tier }));
    };
    ws.onmessage = (ev) => {
      if (typeof ev.data === "string") this.onMessage(JSON.parse(ev.data));
      else this.onBinary(new Uint8Array(ev.data));
    };
    ws.onclose = (ev) => {
      clearInterval(this.pinger);
      this.setListening(false, false);
      if (ev.code === 4401 || ev.code === 4403) {
        this.setState("error", "Not paired — open the pairing link again");
        setTimeout(() => location.assign("/pair"), 2500);
        return;
      }
      this.setState("disconnected");
      const wait = this.backoff + Math.random() * 300;
      this.backoff = Math.min(this.backoff * 2, 8000);
      setTimeout(() => this.connect(), wait);
    };
  }

  send(msg) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(msg)); }
  sendBinary(pcm) {
    if (!this.ws || this.ws.readyState !== 1 || !this.listening) return;
    const frame = new Uint8Array(pcm.byteLength + 1);
    frame[0] = 0x01;
    frame.set(new Uint8Array(pcm.buffer, pcm.byteOffset, pcm.byteLength), 1);
    this.ws.send(frame);
  }

  onMessage(msg) {
    switch (msg.type) {
      case "welcome":
        this.backoff = 500;
        this.device = msg.device;
        store.set("jarvis.device", msg.device);
        $("me").textContent = msg.device;
        this.renderDevices(msg.devices || []);
        this.setState("idle");
        clearInterval(this.pinger);
        this.pinger = setInterval(() => this.send({ type: "ping", t: Date.now() }),
          Math.max(1000, (msg.heartbeat_s || 4) * 1000));
        this.send({ type: "conversation_mode", on: this.conversation });
        break;
      case "devices": this.renderDevices(msg.devices || []); break;
      case "state": this.onHubState(msg.state); break;
      case "active": this.onActive(msg.device); break;
      case "listen": this.setListening(!!msg.on, false); break;
      case "flush": if (this.audio) this.audio.flush(); break;
      case "log": this.addFeed(msg.text, msg.level); break;
      case "action": this.addAction(msg.entry || {}); break;
      case "notify": this.toast(msg.text, msg.speak); break;
      case "show_file": this.openViewer(msg); break;
      case "pong": this.rtt = Date.now() - (msg.t || Date.now()); break;
      default: break;
    }
  }

  onBinary(bytes) {
    if (bytes[0] === 0x01 && this.audio) this.audio.play(bytes.subarray(1));
  }

  // ── state ─────────────────────────────────────────────────────────────────
  onHubState(hubState) {
    if (this.active && this.active !== this.device) return;   // passive devices stay calm
    let s = HUB_STATES[hubState] || "idle";
    if (s === "idle" && this.listening) s = "listening";
    this.setState(s);
  }

  onActive(device) {
    this.active = device || null;
    const chip = $("active");
    chip.hidden = !device;
    chip.textContent = device ? `Active: ${device}` : "";
    document.body.classList.toggle("passive", !!device && device !== this.device);
    if (device !== this.device) {
      this.setListening(false, false);
      if (this.audio) this.audio.flush();
      if (this.state !== "disconnected") this.setState("idle");
    }
  }

  setState(state, label) {
    this.state = state;
    document.body.className = document.body.className.replace(/state-\S+/g, "").trim() + ` state-${state}`;
    this.orb.setState(state);
    $("state-label").textContent = label || STATE_LABELS[state] || state;
  }

  async toggleListening() {
    if (this.state === "disconnected") return;
    if (this.audio) await this.audio.unlock();     // audio needs a user gesture
    this.setListening(!this.listening, true);
  }

  async setListening(on, tell) {
    if (on && this.audio) {
      try { await this.audio.startMic(); } catch (err) {
        this.setState("error", "Microphone blocked — use https or localhost");
        return;
      }
    }
    if (!on && this.audio) this.audio.stopMic();
    this.listening = on;
    if (tell) this.send({ type: on ? "activate" : "deactivate" });
    if (this.state !== "disconnected" && this.state !== "error") this.setState(on ? "listening" : "idle");
  }

  stop() {
    this.send({ type: "stop" });
    if (this.audio) this.audio.flush();
    this.setListening(false, false);
  }

  // ── panels ────────────────────────────────────────────────────────────────
  renderDevices(devices) {
    const box = $("devices");
    box.textContent = "";
    for (const d of devices) {
      const el = document.createElement("span");
      el.className = "dev" + (d.online ? " on" : "") + (d.name === this.device ? " me" : "");
      el.textContent = d.name;
      el.title = d.online ? `online: ${(d.links || []).join(", ")}` : "offline";
      box.appendChild(el);
    }
  }

  addFeed(text, level) {
    if (!text) return;
    const li = document.createElement("li");
    if (level === "error" || /^ERR|failed/i.test(text)) li.className = "error";
    const t = document.createElement("div");
    t.className = "t";
    t.textContent = new Date().toLocaleTimeString();
    li.append(t, document.createTextNode(String(text).slice(0, 400)));
    const feed = $("feed");
    feed.prepend(li);
    while (feed.children.length > 40) feed.lastChild.remove();
  }

  addAction(e) {
    const args = Object.entries(e.args || {}).map(([k, v]) => `${k}=${String(v).slice(0, 40)}`).join(", ");
    const where = e.device && e.device !== "hub" ? ` @${e.device}` : "";
    this.addFeed(`${e.tool}(${args})${where} → ${e.status}: ${String(e.result || "").slice(0, 160)}`,
      e.status === "error" ? "error" : "");
  }

  toast(text, speak) {
    const el = document.createElement("div");
    el.className = "toast";
    el.textContent = text;
    $("toasts").appendChild(el);
    setTimeout(() => el.remove(), 4200);
    if (speak && "speechSynthesis" in window) speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }

  openViewer(msg) {
    const body = $("viewer-body");
    body.textContent = "";
    $("viewer-name").textContent = msg.name || "";
    $("viewer-download").href = msg.url + (msg.url.includes("?") ? "&" : "?") + "download=1";
    const mime = msg.mime || "";
    let el;
    if (mime.startsWith("image/")) { el = document.createElement("img"); el.src = msg.url; }
    else if (mime.startsWith("video/") || mime.startsWith("audio/")) {
      el = document.createElement(mime.startsWith("video/") ? "video" : "audio");
      el.src = msg.url; el.controls = true; el.playsInline = true;
    } else if (mime === "application/pdf" && !/Android/i.test(navigator.userAgent)) {
      el = document.createElement("iframe"); el.src = msg.url;
    } else if (mime === "application/pdf") {
      // Android Chrome has no inline PDF viewer: hand the stream to the system viewer.
      el = document.createElement("button");
      el.className = "stop"; el.style.width = "auto"; el.style.borderRadius = "12px"; el.style.padding = "0 18px";
      el.textContent = "Open PDF";
      el.onclick = () => window.open(msg.url, "_blank");
    }
    else if (mime.startsWith("text/") || /json|xml|csv/.test(mime)) {
      el = document.createElement("pre");
      fetch(msg.url, { headers: { Range: "bytes=0-262143" } }).then((r) => r.text()).then((t) => { el.textContent = t; });
    } else {
      el = document.createElement("p");
      el.textContent = "No preview for this file type — use Download.";
    }
    body.appendChild(el);
    $("viewer").hidden = false;
  }

  closeViewer() { $("viewer").hidden = true; $("viewer-body").textContent = ""; }
}

window.jarvis = new App();
