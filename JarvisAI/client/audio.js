// Audio link: microphone -> 16 kHz PCM16 frames, and 24 kHz PCM16 -> speakers.
// The hub never sends anything but PCM; all keys stay on the hub.
export class AudioLink {
  constructor({ onMicFrame, onLevel, onBuffered } = {}) {
    this.onMicFrame = onMicFrame || (() => {});
    this.onLevel = onLevel || (() => {});
    this.onBuffered = onBuffered || (() => {});
    this.ctx = null;
    this.player = null;
    this.capture = null;
    this.stream = null;
    this.micLevel = 0;
    this.outLevel = 0;
    this.bufferedMs = 0;
  }

  async unlock() {
    if (this.ctx) { if (this.ctx.state === "suspended") await this.ctx.resume(); return; }
    this.ctx = new (window.AudioContext || window.webkitAudioContext)({ latencyHint: "interactive" });
    await this.ctx.audioWorklet.addModule("/static/audio-worklet.js");
    this.player = new AudioWorkletNode(this.ctx, "jarvis-player", { outputChannelCount: [2] });
    this.player.port.onmessage = (e) => {
      this.outLevel = e.data.level || 0;
      this.bufferedMs = e.data.bufferedMs || 0;
      this.onBuffered(this.bufferedMs);
      this.onLevel(Math.max(this.outLevel, this.micLevel));
    };
    this.player.connect(this.ctx.destination);
  }

  async startMic() {
    await this.unlock();
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
    });
    const src = this.ctx.createMediaStreamSource(this.stream);
    this.capture = new AudioWorkletNode(this.ctx, "jarvis-capture");
    this.capture.port.onmessage = (e) => {
      if (e.data.pcm) this.onMicFrame(e.data.pcm);
      else if (e.data.level !== undefined) { this.micLevel = e.data.level; this.onLevel(Math.max(this.outLevel, this.micLevel)); }
    };
    src.connect(this.capture);
    this._src = src;
  }

  stopMic() {
    if (this._src) { try { this._src.disconnect(); } catch { /* already gone */ } this._src = null; }
    if (this.capture) { this.capture.port.onmessage = null; this.capture = null; }
    if (this.stream) { for (const t of this.stream.getTracks()) t.stop(); this.stream = null; }
    this.micLevel = 0;
  }

  // pcm: Uint8Array of little-endian int16 at 24 kHz.
  play(pcm) {
    if (!this.player) return;
    const n = pcm.byteLength >> 1;
    const view = new DataView(pcm.buffer, pcm.byteOffset, n * 2);
    const ratio = this.ctx.sampleRate / 24000;
    const outLen = Math.round(n * ratio);
    const out = new Float32Array(outLen);
    for (let i = 0; i < outLen; i++) {      // linear interpolation up to the device rate
      const x = i / ratio, i0 = Math.floor(x), f = x - i0;
      const a = view.getInt16(Math.min(i0, n - 1) * 2, true) / 32768;
      const b = view.getInt16(Math.min(i0 + 1, n - 1) * 2, true) / 32768;
      out[i] = a + (b - a) * f;
    }
    this.player.port.postMessage({ samples: out }, [out.buffer]);
  }

  flush() { if (this.player) this.player.port.postMessage({ flush: true }); }
}
