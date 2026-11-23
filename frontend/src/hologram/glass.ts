import { AdditiveBlending, Color, ShaderMaterial } from 'three';
import { compose, DISPLACEMENT, FRESNEL, GLITCH, KEY_LIGHT, SCANLINES, SURFACE_PULSE } from './shaders/chunks';

/** Tunable look of the glass material (all optional). */
export interface GlassParams {
    bodyAlpha?: number; // how much the surface itself glows (0 = clear)
    power?: number; // fresnel sharpness
    shade?: number; // soft key light so features read (0 = none)
    scan?: number; // projector scanline strength 0..1
    pulse?: number; // travelling surface pulse strength 0..1
    displace?: number; // vertex breathing along the normal (world units, 0 = none)
}

/**
 * Hologram glass: nearly clear where the surface faces you, glowing at the silhouette (fresnel),
 * with optional key light, scanlines, a travelling pulse, rare glitch bands and vertex breathing.
 * Drawn additively, so it emits light instead of covering what is behind it. Uniforms `time`,
 * `boost` (voice/energy) and `glitch` (chance per 1/8 s, 0 = never) are driven by the scene.
 */
export function glassMaterial(rim: Color, body: Color, p: GlassParams = {}): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: {
            rim: { value: rim.clone() },
            body: { value: body.clone() },
            bodyAlpha: { value: p.bodyAlpha ?? 0.1 },
            power: { value: p.power ?? 2.2 },
            shade: { value: p.shade ?? 0 },
            scan: { value: p.scan ?? 0.12 },
            pulse: { value: p.pulse ?? 0.15 },
            displace: { value: p.displace ?? 0 },
            boost: { value: 0 },
            time: { value: 0 },
            glitch: { value: 0 },
        },
        vertexShader: compose(
            [DISPLACEMENT],
            /* glsl */ `
      uniform float time; uniform float displace;
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main() {
        vec3 p = holoDisplace(position, normal, time, displace);
        vec4 mv = modelViewMatrix * vec4(p, 1.0);
        vN = normalize(normalMatrix * normal);
        vV = normalize(-mv.xyz);
        vP = position;
        gl_Position = projectionMatrix * mv;
      }`,
        ),
        fragmentShader: compose(
            [FRESNEL, KEY_LIGHT, SCANLINES, SURFACE_PULSE, GLITCH],
            /* glsl */ `
      uniform vec3 rim; uniform vec3 body; uniform float bodyAlpha; uniform float power; uniform float boost;
      uniform float shade; uniform float scan; uniform float pulse; uniform float time; uniform float glitch;
      varying vec3 vN; varying vec3 vV; varying vec3 vP;
      void main() {
        float f = holoFresnel(vN, vV, power);
        float lit = shade * holoKeyLight(vN);
        vec3 c = mix(body, rim, f) + rim * lit;
        float a = clamp(bodyAlpha + lit * 0.55 + f * (0.85 + boost), 0.0, 1.0);
        a *= 1.0 - scan + scan * holoScanlines(vP.y, time, 28.0, 0.15);
        a *= 1.0 - pulse + pulse * surfacePulse(vP, time, 3.0);
        float g = glitchBand(vP.y, time, glitch);
        c = mix(c, vec3(1.0), g * 0.5); a = clamp(a + g * 0.4, 0.0, 1.0);
        gl_FragColor = vec4(c * a, a);
      }`,
        ),
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}

/** Points that twinkle on their own phase (attribute `phase`), sized in world units. */
export function twinkleMaterial(color: Color, size: number, base = 0.35): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: { color: { value: color.clone() }, size: { value: size }, time: { value: 0 }, base: { value: base }, gain: { value: 1 } },
        vertexShader: /* glsl */ `
      attribute float phase; uniform float size; uniform float time; varying float vA;
      uniform float base; uniform float gain;
      void main() {
        vec4 mv = modelViewMatrix * vec4(position, 1.0);
        float tw = 0.5 + 0.5 * sin(time * (1.2 + fract(phase * 7.3) * 2.0) + phase * 6.283);
        vA = (base + (1.0 - base) * pow(tw, 3.0)) * gain;
        gl_PointSize = size * (300.0 / -mv.z) * (0.6 + 0.8 * tw);
        gl_Position = projectionMatrix * mv;
      }`,
        fragmentShader: /* glsl */ `
      uniform vec3 color; varying float vA;
      void main() {
        float d = length(gl_PointCoord - 0.5);
        float a = smoothstep(0.5, 0.0, d) * vA;
        gl_FragColor = vec4(color * a, a);
      }`,
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}

/** Deterministic random numbers, so the brain, the plexus and the dust look the same every launch. */
export function rng(seed: number) {
    let s = seed >>> 0;
    return () => {
        s = (s * 1664525 + 1013904223) >>> 0;
        return s / 4294967296;
    };
}
