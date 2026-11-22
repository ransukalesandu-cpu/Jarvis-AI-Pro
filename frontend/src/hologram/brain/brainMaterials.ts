/**
 * GPU materials for the neural brain. Everything that makes it "live" runs in the shaders:
 * nodes fire on their own clocks, synapses grow out from a node, carry signals and dissolve while
 * others form, and lobes glow with the assistant's state. `target` + `morph` let every node flow
 * into another shape (morph 0 = brain, 1 = target).
 */
import { AdditiveBlending, Color, ShaderMaterial } from 'three';
import { CIRCUIT_FLOW, compose } from '../shaders/chunks';

const LOBE_LOOKUP = /* glsl */ `
uniform float lobeLevel[6];
float lobeAct(float lobe) {
  int i = int(lobe + 0.5);
  float v = lobeLevel[0];
  if (i == 1) v = lobeLevel[1]; else if (i == 2) v = lobeLevel[2]; else if (i == 3) v = lobeLevel[3];
  else if (i == 4) v = lobeLevel[4]; else if (i == 5) v = lobeLevel[5];
  return v;
}`;

const common = () => ({
  time: { value: 0 }, morph: { value: 0 }, lobeLevel: { value: [0.25, 0.25, 0.25, 0.25, 0.25, 0.3] },
  tint: { value: new Color(1, 1, 1) },
});

export function nodeMaterial(color: Color, core: Color): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { ...common(), color: { value: color.clone() }, core: { value: core.clone() }, firing: { value: 0.25 }, scale: { value: 1000 }, size: { value: 0.016 } },
    vertexShader: LOBE_LOOKUP + /* glsl */ `
      attribute vec3 target; attribute float lobe; attribute float phase;
      uniform float time; uniform float morph; uniform float firing; uniform float scale; uniform float size;
      varying float vGlow; varying float vFire;
      void main() {
        vec3 p = mix(position, target, morph);
        float act = lobeAct(lobe) * (0.65 + 0.35 * sin(time * 2.0 + position.x * 5.0 + position.y * 3.0));
        float clock = fract(time * (0.35 + phase * 0.5) + phase * 17.0);
        float fire = (1.0 - smoothstep(0.0, 0.06, clock)) * step(phase, 0.15 + firing * 0.85);  // a share of nodes fire
        vGlow = 0.35 + 0.65 * act; vFire = fire;
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        gl_PointSize = size * (1.0 + fire * 1.6 + act * 0.4) * scale / -mv.z;
        gl_Position = projectionMatrix * mv;
      }`,
    fragmentShader: /* glsl */ `
      uniform vec3 color; uniform vec3 core; uniform vec3 tint;
      varying float vGlow; varying float vFire;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float disc = smoothstep(0.5, 0.15, d);
        float a = clamp(disc * (vGlow + vFire), 0.0, 1.0);
        vec3 c = mix(color, core, clamp(vFire + smoothstep(0.2, 0.0, d) * 0.6, 0.0, 1.0)) * tint;
        gl_FragColor = vec4(c * a, a);
      }`,
    transparent: true, depthWrite: false, blending: AdditiveBlending,
  });
}

export function synapseMaterial(color: Color, core: Color): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { ...common(), color: { value: color.clone() }, core: { value: core.clone() }, growth: { value: 0.45 }, flow: { value: 0.4 } },
    vertexShader: LOBE_LOOKUP + /* glsl */ `
      attribute vec3 target; attribute float along; attribute float phase; attribute float rate; attribute float lobe; attribute float span;
      uniform float time; uniform float morph;
      varying float vAlong; varying float vPhase; varying float vAct; varying float vLife; varying float vSpan;
      void main() {
        vAlong = along; vPhase = phase; vAct = lobeAct(lobe);
        vLife = fract(time * rate + phase);
        vSpan = span;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(mix(position, target, morph), 1.0);
      }`,
    fragmentShader: compose([CIRCUIT_FLOW], /* glsl */ `
      uniform vec3 color; uniform vec3 core; uniform vec3 tint; uniform float time; uniform float growth; uniform float flow; uniform float morph;
      varying float vAlong; varying float vPhase; varying float vAct; varying float vLife; varying float vSpan;
      void main() {
        // A synapse is alive for a share (growth) of its cycle: it grows out from its node, holds, dissolves.
        if (vLife > growth) discard;
        float grown = clamp(vLife / (growth * 0.25 + 0.001), 0.0, 1.0);
        if (vAlong > grown) discard;
        float fade = smoothstep(growth, growth * 0.75, vLife);
        float pulse = circuitFlow(vAlong + vPhase, time, flow * 0.5, 1.0);
        float a = fade * (0.05 + 0.25 * vAct + pulse * (0.45 + vAct)) * (1.0 - morph * smoothstep(0.15, 0.4, vSpan));
        vec3 c = mix(color, core, pulse) * tint;
        gl_FragColor = vec4(c * a, a);
      }`),
    transparent: true, depthWrite: false, blending: AdditiveBlending,
  });
}

/** Soft glow behind the brain so it reads as one luminous object. */
export function haloMaterial(color: Color): ShaderMaterial {
  return new ShaderMaterial({
    uniforms: { color: { value: color.clone() }, strength: { value: 0.2 }, tint: { value: new Color(1, 1, 1) } },
    vertexShader: /* glsl */ `varying vec2 vUv; void main() { vUv = uv; gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0); }`,
    fragmentShader: /* glsl */ `
      uniform vec3 color; uniform float strength; uniform vec3 tint; varying vec2 vUv;
      void main() { float d = length(vUv - 0.5) * 2.0; float a = pow(max(0.0, 1.0 - d), 2.2) * strength; gl_FragColor = vec4(color * tint * a, a); }`,
    transparent: true, depthWrite: false, blending: AdditiveBlending,
  });
}
