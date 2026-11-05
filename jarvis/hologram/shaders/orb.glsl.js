import { UNIFORM_DECL, HELPERS } from './common.glsl.js';
const HEAD = `${UNIFORM_DECL}\n${HELPERS}\n`;

// Energy lattice points on the sphere: latitude bands, listening ripples, speaking pulses.
export const points = {
  vert: HEAD + /* glsl */ `
attribute float aSeed; attribute float aSize;
varying float vSeed; varying float vBand; varying float vF;
void main(){
  vec3 n = normalize(position);
  float band = 0.5 + 0.5 * sin(n.y * 9.0 + uTime * (0.8 + uOrb * 2.4) + aSeed * 3.0);
  float ripple = sin(n.y * 7.0 - uTime * 9.0) * uListen * 0.10;
  float pulse = uSpeak * 0.10 * sin(uTime * 14.0 + n.y * 4.0 + aSeed * 6.0) + uSpeak * 0.05;
  float r = 1.0 + 0.035 * band * (0.3 + uOrb) + ripple + pulse;
  vec3 p = n * r;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vSeed = aSeed; vBand = band;
  vF = clamp(normalize(normalMatrix * n).z, -1.0, 1.0);
  gl_PointSize = max(1.0, aSize * (0.7 + 0.6 * band) * uPointScale / max(0.1, -mv.z));
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vSeed; varying float vBand; varying float vF;
void main(){
  float d = length(gl_PointCoord - 0.5);
  float a = smoothstep(0.5, 0.0, d); a *= a;
  vec3 col = mix(uOrbC, uOrbCore, vBand * 0.7 + 0.15);
  float rim = 0.45 + 0.55 * (1.0 - abs(vF));
  float k = (0.5 + 0.9 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * rim * (0.35 + 0.65 * vBand) * k);
}`,
};

// Rotating neural lattice lines.
export const lattice = {
  vert: HEAD + /* glsl */ `
varying float vY; varying float vF; varying float vR;
uniform float uRadius;
void main(){
  vec3 p = position * uRadius;
  vec4 mv = modelViewMatrix * vec4(p, 1.0);
  vec3 n = normalize(normalMatrix * normalize(position));
  vF = clamp(n.z, -1.0, 1.0); vY = position.y; vR = uRadius;
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying float vY; varying float vF; varying float vR;
void main(){
  float wave = smoothstep(0.7, 1.0, sin(vY * 6.0 - uTime * (1.0 + uOrb * 3.0)));
  float a = (0.14 + 0.5 * wave) * (0.45 + 0.55 * (1.0 - abs(vF)) + 0.2);
  vec3 col = mix(uOrbC, uOrbCore, wave);
  float k = (0.55 + 0.8 * uEnergy) * uGlow * (vR > 0.9 ? 1.0 : 0.8);
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};

// Luminous core.
export const core = {
  vert: HEAD + /* glsl */ `
varying vec3 vN; varying vec3 vV;
void main(){
  float pulse = 1.0 + 0.10 * uSpeak + 0.05 * sin(uTime * (1.6 + uOrb * 3.0)) + 0.06 * uListen;
  vec4 mv = modelViewMatrix * vec4(position * pulse, 1.0);
  vN = normalize(normalMatrix * normal); vV = -mv.xyz;
  gl_Position = projectionMatrix * mv;
}`,
  frag: HEAD + /* glsl */ `
varying vec3 vN; varying vec3 vV;
void main(){
  float f = pow(abs(dot(normalize(vN), normalize(vV))), 1.6);
  vec3 col = mix(uOrbC, uOrbCore, f);
  float k = (0.55 + 0.9 * uEnergy + 0.5 * uSpeak) * uGlow;
  gl_FragColor = vec4(tint(col) * k, (0.12 + 0.5 * f) * k);
}`,
};

// Orbital ring lines with a bright traveling segment.
export const ring = {
  vert: HEAD + /* glsl */ `
attribute float aT;
varying float vT;
void main(){ vT = aT; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
  frag: HEAD + /* glsl */ `
varying float vT;
void main(){
  float head = fract(uTime * (0.12 + uOrb * 0.35));
  float d = abs(fract(vT - head + 0.5) - 0.5);
  float a = 0.14 + 0.8 * exp(-d * d * 400.0);
  vec3 col = mix(uOrbC, uOrbCore, exp(-d * d * 400.0));
  float k = (0.55 + 0.8 * uEnergy) * uGlow;
  gl_FragColor = vec4(tint(col) * k, a * k);
}`,
};
