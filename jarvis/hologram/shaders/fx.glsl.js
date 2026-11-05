import { UNIFORM_DECL, HELPERS } from './common.glsl.js';
const HEAD = `${UNIFORM_DECL}\n${HELPERS}\n`;

// Energy wires: static curve lines with a traveling pulse...
export const wireLine = {
  vert: HEAD + /* glsl */ `
attribute float aT; attribute float aSeed; attribute float aKind;
varying float vT; varying float vSeed; varying float vKind;
void main(){ vT = aT; vSeed = aSeed; vKind = aKind; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  frag: HEAD + /* glsl */ `
varying float vT; varying float vSeed; varying float vKind;
vec3 endColor(float k, float t){
  // kind 0: heart -> face, 1: face -> orb, 2: heart -> orb
  vec3 a = k < 0.5 ? uHeartC : (k < 1.5 ? uWireC : uHeartC);
  vec3 b = k < 0.5 ? uWireC : (k < 1.5 ? uOrbC : uOrbC);
  return mix(a, b, smoothstep(0.1, 0.9, t));
}
void main(){
  float head = fract(uTime * (0.10 + uFlow * 0.35) + vSeed);
  float d = abs(fract(vT - head + 0.5) - 0.5);
  float pulse = exp(-d * d * 220.0);
  float a = 0.10 + 0.10 * uFlow + 0.85 * pulse * (0.3 + uFlow);
  vec3 col = mix(endColor(vKind, vT), uSpark, pulse * 0.6);
  float k = (0.55 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// ...and particles that flow along the same cubic curves, positioned entirely on the GPU.
export const wireParticles = {
  vert: HEAD + /* glsl */ `
attribute vec3 aP0; attribute vec3 aP1; attribute vec3 aP2; attribute vec3 aP3;
attribute float aPhase; attribute float aSeed; attribute float aKind;
varying float vT; varying float vKind; varying float vSeed;
vec3 bez(float t){ float u = 1.0 - t; return u*u*u*aP0 + 3.0*u*u*t*aP1 + 3.0*u*t*t*aP2 + t*t*t*aP3; }
void main(){
  float speed = 0.06 + uFlow * 0.30 + (uSpeak + uListen) * 0.2;
  float t = fract(aPhase + uTime * speed * (0.7 + aSeed * 0.6));
  vec3 p = bez(t);
  p += vec3(sin(uTime * 2.0 + aSeed * 30.0), cos(uTime * 1.7 + aSeed * 20.0), 0.0) * 0.012;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vT = t; vKind = aKind; vSeed = aSeed;
  float env = sin(t * 3.14159);
  gl_PointSize = max(1.0, (0.030 + 0.030 * uFlow) * (0.5 + env) * uPointScale / max(0.1, -mv.z));
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vT; varying float vKind; varying float vSeed;
void main(){
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d); a *= a;
  vec3 s = vKind < 0.5 ? uHeartHot : uSpark;
  vec3 col = mix(vKind > 0.5 && vKind < 1.5 ? uOrbCore : uWireC, s, 0.4);
  col = mix(vKind < 0.5 || vKind > 1.5 ? uHeartSoft : col, col, smoothstep(0.1, 0.8, vT));
  float k = (0.6 + 0.9 * uEnergy) * uGlow * (0.4 + 0.8 * uFlow);
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// Orbital aura rings around the bust (ellipse lines with a traveling highlight).
export const auraRing = {
  vert: HEAD + /* glsl */ `
attribute float aT;
uniform float uRingSeed;
varying float vT;
void main(){ vT = aT; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  frag: HEAD + /* glsl */ `
uniform float uRingSeed;
varying float vT;
void main(){
  float head = fract(uTime * (0.03 + uRing * 0.14) * (mod(uRingSeed, 2.0) < 1.0 ? 1.0 : -1.0) + uRingSeed * 0.37);
  float d = abs(fract(vT - head + 0.5) - 0.5);
  float glow = exp(-d * d * 180.0);
  float a = 0.07 + 0.08 * uRing + 0.75 * glow * (0.35 + uRing);
  vec3 col = mix(uRingC, uSpark, glow * 0.7);
  float k = (0.45 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// Base disc: concentric rings on the floor plane.
export const base = {
  vert: HEAD + /* glsl */ `
attribute float aR;
varying float vR;
void main(){ vR = aR; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  frag: HEAD + /* glsl */ `
varying float vR;
void main(){
  float wave = 0.5 + 0.5 * sin(vR * 14.0 - uTime * (0.8 + uRing * 2.0));
  float a = (0.18 + 0.5 * wave * (0.3 + uRing)) * (1.0 - vR * 0.45);
  vec3 col = mix(uRingC, uSpark, wave * 0.4);
  float k = (0.55 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// Vertical data lines and drifting sparks in the background.
export const dataLine = {
  vert: HEAD + /* glsl */ `
attribute float aT; attribute float aSeed;
varying float vT; varying float vSeed;
void main(){ vT = aT; vSeed = aSeed; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  frag: HEAD + /* glsl */ `
varying float vT; varying float vSeed;
void main(){
  float head = fract(uTime * (0.05 + 0.18 * uRing) * (0.5 + vSeed) + vSeed * 9.0);
  float d = abs(vT - head);
  float a = 0.035 + 0.5 * exp(-d * d * 260.0) * (0.3 + uRing);
  float k = (0.45 + 0.7 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(mix(uRingC, uSpark, 0.3)) * k, a * k);
}`,
};

export const sparks = {
  vert: HEAD + /* glsl */ `
attribute float aSeed; attribute float aSize;
varying float vA;
void main(){
  vec3 p = position;
  p.y = mod(p.y + 2.6 + uTime * (0.03 + 0.05 * uRing) * (0.5 + aSeed), 4.2) - 2.7;
  p.x += sin(uTime * 0.4 + aSeed * 30.0) * 0.05;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vA = smoothstep(-2.7, -2.2, p.y) * (1.0 - smoothstep(1.2, 1.6, p.y)) * (0.4 + 0.6 * sin(uTime + aSeed * 40.0) * sin(uTime + aSeed * 40.0));
  gl_PointSize = max(1.0, aSize * uPointScale / max(0.1, -mv.z));
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vA;
void main(){
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d); a *= a * vA;
  float k = (0.5 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(uSpark) * k, a * k);
}`,
};
