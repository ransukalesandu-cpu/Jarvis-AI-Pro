import { AdditiveBlending, Color, ShaderMaterial } from 'three';
import { compose, DISPLACEMENT, FRESNEL, GLITCH, KEY_LIGHT, SCANLINES, SURFACE_PULSE } from './shaders/chunks';
import { GLSL } from './shaders/glsl.generated';

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
        vertexShader: compose([DISPLACEMENT], GLSL['glass.vert']),
        fragmentShader: compose([FRESNEL, KEY_LIGHT, SCANLINES, SURFACE_PULSE, GLITCH], GLSL['glass.frag']),
        transparent: true,
        depthWrite: false,
        blending: AdditiveBlending,
    });
}

/** Points that twinkle on their own phase (attribute `phase`), sized in world units. */
export function twinkleMaterial(color: Color, size: number, base = 0.35): ShaderMaterial {
    return new ShaderMaterial({
        uniforms: { color: { value: color.clone() }, size: { value: size }, time: { value: 0 }, base: { value: base }, gain: { value: 1 } },
        vertexShader: GLSL['glass.twinkle.vert'],
        fragmentShader: GLSL['glass.twinkle.frag'],
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
