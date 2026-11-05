// AudioWorklet processors. Capture: downsample the mic to 16 kHz mono PCM16 and
// post ~20 ms frames. Player: a small jitter buffer that can be flushed at once.

class CaptureProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / 16000;
    this.frame = new Int16Array(320);       // 20 ms at 16 kHz
    this.fill = 0;
    this.pos = 0;                           // fractional read position
    this.acc = 0; this.accN = 0;
    this.level = 0;
  }
  process(inputs) {
    const ch = inputs[0] && inputs[0][0];
    if (!ch) return true;
    let sum = 0;
    for (let i = 0; i < ch.length; i++) {
      const s = ch[i];
      sum += s * s;
      // Box-filter the samples that fall into one output sample (anti-alias).
      this.acc += s; this.accN += 1;
      this.pos += 1;
      if (this.pos >= this.ratio) {
        this.pos -= this.ratio;
        const v = Math.max(-1, Math.min(1, this.acc / this.accN));
        this.acc = 0; this.accN = 0;
        this.frame[this.fill++] = v < 0 ? v * 0x8000 : v * 0x7fff;
        if (this.fill === this.frame.length) {
          this.port.postMessage({ pcm: this.frame.slice(0) }, []);
          this.fill = 0;
        }
      }
    }
    this.level = Math.sqrt(sum / ch.length);
    this.port.postMessage({ level: this.level });
    return true;
  }
}

class PlayerProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.buf = new Float32Array(sampleRate * 30);   // 30 s ring buffer
    this.read = 0; this.write = 0;
    this.started = false;
    this.startAt = Math.round(sampleRate * 0.06);   // 60 ms jitter buffer
    this.reportIn = 0;
    this.port.onmessage = (e) => {
      const m = e.data;
      if (m.flush) { this.read = this.write = 0; this.started = false; return; }
      if (m.samples) {
        const s = m.samples;
        for (let i = 0; i < s.length; i++) { this.buf[this.write] = s[i]; this.write = (this.write + 1) % this.buf.length; }
      }
    };
  }
  available() { return (this.write - this.read + this.buf.length) % this.buf.length; }
  process(_inputs, outputs) {
    const out = outputs[0][0];
    let have = this.available();
    if (!this.started && have >= this.startAt) this.started = true;
    let sum = 0;
    for (let i = 0; i < out.length; i++) {
      if (this.started && have > 0) {
        const v = this.buf[this.read]; this.read = (this.read + 1) % this.buf.length; have--;
        out[i] = v; sum += v * v;
      } else {
        out[i] = 0;
        if (this.started && have === 0) this.started = false;     // underrun: re-buffer
      }
    }
    for (let c = 1; c < outputs[0].length; c++) outputs[0][c].set(out);
    if (++this.reportIn >= 8) {      // ~ every 20 ms at 128-sample quanta
      this.reportIn = 0;
      this.port.postMessage({ level: Math.sqrt(sum / out.length), bufferedMs: (have / sampleRate) * 1000 });
    }
    return true;
  }
}

registerProcessor("jarvis-capture", CaptureProcessor);
registerProcessor("jarvis-player", PlayerProcessor);
