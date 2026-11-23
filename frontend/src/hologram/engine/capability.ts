/**
 * Can this page draw the 3D hologram? Probed once with a throwaway canvas. The answer goes to Python
 * (`hologram.capability`), which falls back to the classic HUD when it is false.
 */
let cached: boolean | null = null;

export function hasWebGL2(make: () => HTMLCanvasElement = () => document.createElement('canvas')): boolean {
    if (cached !== null) return cached;
    try {
        const gl = make().getContext('webgl2');
        cached = !!gl;
        gl?.getExtension('WEBGL_lose_context')?.loseContext(); // give the probe context back at once
    } catch {
        cached = false;
    }
    return cached;
}

/** Tests only. */
export function resetCapability(): void {
    cached = null;
}
