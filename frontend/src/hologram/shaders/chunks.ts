/**
 * The hologram's GLSL library: one concern per chunk, plain functions only (no uniforms, no main),
 * so any material can compose what it needs. Sources live in ./lib/*.glsl (hash/noise from LYGIA via
 * #include) and are resolved by scripts/build-shaders.mjs into glsl.generated.ts. Every chunk is compiled
 * in a real WebGL2 context by scripts/check_shaders.py, and its shape is unit-tested.
 */
import { GLSL } from './glsl.generated';

/** Edge glow: 0 facing the viewer, 1 at the silhouette. */
export const FRESNEL = GLSL['lib/fresnel'];
/** Soft key light from the upper left so features read through the glass (0..~1). */
export const KEY_LIGHT = GLSL['lib/key-light'];
/** Energy running along a 0..1 parameter: bright packets that move with time. */
export const CIRCUIT_FLOW = GLSL['lib/circuit-flow'];
/** Horizontal projector lines drifting slowly (y in world or screen units). */
export const SCANLINES = GLSL['lib/scanlines'];
/** A slow wave of brightness travelling over the surface. */
export const SURFACE_PULSE = GLSL['lib/surface-pulse'];
/** Controlled glitch: rare, short bands. Returns 0 (no glitch) or a band intensity 0..1. */
export const GLITCH = GLSL['lib/glitch'];
/** Subtle breathing displacement along the normal (amount 0 = none). */
export const DISPLACEMENT = GLSL['lib/displacement'];
/** Eye emission: iris fibres, limbal ring, dilating pupil, glint, turning scan ring, socket glow. */
export const EYE_EMISSION = GLSL['lib/eye-emission'];

export const CHUNKS = { FRESNEL, KEY_LIGHT, CIRCUIT_FLOW, SCANLINES, SURFACE_PULSE, GLITCH, DISPLACEMENT, EYE_EMISSION } as const;
export type ChunkName = keyof typeof CHUNKS;

/** Joins chunks (each once, in order) ahead of a shader body. */
export function compose(chunks: string[], body: string): string {
    return [...new Set(chunks)].join('\n') + '\n' + body;
}
