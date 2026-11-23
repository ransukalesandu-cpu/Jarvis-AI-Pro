import { describe, expect, it } from 'vitest';
import { CHUNKS, compose } from './chunks';

const FUNCS: Record<keyof typeof CHUNKS, string> = {
    FRESNEL: 'float holoFresnel(',
    KEY_LIGHT: 'float holoKeyLight(',
    CIRCUIT_FLOW: 'float circuitFlow(',
    SCANLINES: 'float holoScanlines(',
    SURFACE_PULSE: 'float surfacePulse(',
    GLITCH: 'float glitchBand(',
    DISPLACEMENT: 'vec3 holoDisplace(',
    EYE_EMISSION: 'vec4 eyeEmission(',
};

describe('GLSL chunk library', () => {
    it('each chunk defines its function and nothing global besides functions', () => {
        for (const [name, src] of Object.entries(CHUNKS)) {
            expect(src, name).toContain(FUNCS[name as keyof typeof CHUNKS]);
            expect(src, name).not.toMatch(/\buniform\b|\bvarying\b|void main/);
            expect(src.split('{').length, name).toBe(src.split('}').length); // balanced braces
        }
    });
    it('compose includes each chunk once, before the body', () => {
        const out = compose([CHUNKS.FRESNEL, CHUNKS.GLITCH, CHUNKS.FRESNEL], 'void main(){}');
        expect(out.split('holoFresnel(').length - 1).toBe(1);
        expect(out.indexOf('glitchBand(')).toBeLessThan(out.indexOf('void main'));
    });
});
