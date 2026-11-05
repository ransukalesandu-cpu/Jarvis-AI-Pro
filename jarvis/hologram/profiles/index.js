import jarvis from './jarvis.js';
import bihansa from './bihansa.js';
import { damp } from '../animation/transitions.js';

export const PROFILES = Object.freeze({ jarvis, bihansa });
const NUM_KEYS = ['shape', 'hairLen', 'hairSwirl', 'pulseRate', 'glow'];
const COLOR_KEYS = ['face', 'faceDeep', 'hair', 'wire', 'spark', 'heart', 'heartHot', 'heartSoft', 'orb', 'orbCore', 'ring'];

/** Smoothly blended profile values; switching never rebuilds anything. */
export class ProfileBlend {
  constructor(id = 'jarvis') {
    this.id = id;
    this.cur = { id };
    for (const k of COLOR_KEYS) this.cur[k] = [...PROFILES[id][k]];
    for (const k of NUM_KEYS) this.cur[k] = PROFILES[id][k];
  }
  set(id) { if (PROFILES[id]) this.id = id; }
  update(dt, rate = 3.0) {
    const t = PROFILES[this.id];
    for (const k of COLOR_KEYS) for (let i = 0; i < 3; i++) this.cur[k][i] = damp(this.cur[k][i], t[k][i], rate, dt);
    for (const k of NUM_KEYS) this.cur[k] = damp(this.cur[k], t[k], rate, dt);
    return this.cur;
  }
  settled() {
    const t = PROFILES[this.id];
    return COLOR_KEYS.every((k) => this.cur[k].every((v, i) => Math.abs(v - t[k][i]) < 0.01))
      && NUM_KEYS.every((k) => Math.abs(this.cur[k] - t[k]) < 0.01);
  }
}
