import { UNIFORM_DECL, HELPERS } from './common.glsl.js';
const HEAD = `${UNIFORM_DECL}\n${HELPERS}\n`;
const BEAT = /* glsl */ `
float beat(){
  float ph = fract(uTime * (0.85 + uHeart * 1.25) * uPulseRate);
  return exp(-pow((ph - 0.06) / 0.07, 2.0)) + 0.62 * exp(-pow((ph - 0.31) / 0.09, 2.0));
}`;

// Heart body points: points on the heart surface with a quantum shimmer.
export const points = {
  vert: HEAD + BEAT + /* glsl */ `
attribute float aSeed; attribute float aSize;
varying float vSeed; varying float vB; varying float vH;
void main(){
  float b = beat();
  vec3 p = position * (1.0 + 0.10 * b + 0.015 * sin(uTime * 1.3));
  p += normalize(position + 1e-4) * 0.03 * sin(uTime * 2.0 + aSeed * 40.0) * (0.4 + uHeart);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vSeed = aSeed; vB = b; vH = position.y;
  gl_PointSize = max(1.0, aSize * (1.0 + 0.5 * b) * uPointScale / max(0.1, -mv.z));
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vSeed; varying float vB; varying float vH;
void main(){
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d); a *= a;
  float m = 0.5 + 0.5 * sin(uTime * 0.7 + vSeed * 30.0 + vH * 2.0);
  vec3 col = mix(uHeartC, uHeartSoft, m * 0.6);
  col = mix(col, uHeartHot, smoothstep(0.55, 1.0, fract(vSeed * 7.0 + uTime * 0.05)) * 0.7);
  col += uSpark * 0.15 * vB;
  float k = (0.55 + 0.7 * uEnergy + 0.5 * vB) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * (0.55 + 0.45 * vB) * k);
}`,
};

// Neural mesh between nearby heart points.
export const mesh = {
  vert: HEAD + BEAT + /* glsl */ `
attribute float aSeed;
varying float vSeed; varying float vB;
void main(){
  float b = beat();
  vec3 p = position * (1.0 + 0.10 * b + 0.015 * sin(uTime * 1.3));
  vSeed = aSeed; vB = b;
  gl_Position = projectionMatrix * modelViewMatrix * vec4(p, 1.0);
}`,
  frag: HEAD + /* glsl */ `
varying float vSeed; varying float vB;
void main(){
  float fire = smoothstep(0.8, 1.0, sin(uTime * (0.6 + uHeart) + vSeed * 40.0));
  float a = 0.16 + 0.55 * fire + 0.25 * vB;
  vec3 col = mix(uHeartC, uHeartHot, fire);
  float k = (0.5 + 0.7 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// Orbiting quantum particles on tilted ellipses.
export const orbit = {
  vert: HEAD + BEAT + /* glsl */ `
attribute float aSeed; attribute float aPhase; attribute vec3 aAxis; attribute float aRad;
varying float vSeed;
void main(){
  float b = beat();
  float ang = aPhase * 6.2831853 + uTime * (0.5 + uHeart * 1.1) * (aSeed > 0.5 ? 1.0 : -1.0);
  vec3 u = normalize(cross(aAxis, vec3(0.0, 1.0, 0.0001)));
  vec3 v = normalize(cross(aAxis, u));
  vec3 p = (u * cos(ang) + v * sin(ang)) * aRad * (1.0 + 0.05 * b);
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vSeed = aSeed;
  gl_PointSize = max(1.0, 0.045 * (1.0 + b) * uPointScale / max(0.1, -mv.z));
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vSeed;
void main(){
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d);
  vec3 col = mix(uHeartHot, uSpark, 0.4);
  float k = (0.6 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * a * k);
}`,
};
