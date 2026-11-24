// UI P4 gates for the 3D layer that can run without a GPU (draw calls and shader compiles run in
// scripts/check_budget.py and scripts/check_shaders.py against real WebGL2).
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { clampDpr, stageLabel } from '../HologramScene';
import { GLSL } from '../shaders/glsl.generated';

const HOLO = join(__dirname, '..');
const walk = (d: string): string[] => readdirSync(d).flatMap((n) => (statSync(join(d, n)).isDirectory() ? walk(join(d, n)) : [join(d, n)]));

describe('3D layer', () => {
    it('pixel ratio stays between 1 and 1.5', () => {
        expect(clampDpr([1, 2])).toEqual([1, 1.5]);
        expect(clampDpr(1)).toEqual([1, 1]);
        expect(clampDpr([0.5, 1.2])).toEqual([1, 1.2]);
    });
    it('the canvas has a text alternative that follows the state', () => {
        expect(stageLabel('brain', 'circuit', 'thinking')).toBe('JARVIS hologram: a living neural brain above a glowing orb. JARVIS is thinking.');
        expect(stageLabel('hologram', 'mechanical', 'idle')).toContain('mechanical hologram head');
    });
    it('shader sources are .glsl files; no GLSL left inline in TypeScript', () => {
        const inline = walk(HOLO).filter((f) => /\.(ts|tsx)$/.test(f) && !f.endsWith('.generated.ts') && !f.includes('.test.'));
        expect(inline.filter((f) => readFileSync(f, 'utf8').includes('/* glsl */'))).toEqual([]);
        expect(Object.keys(GLSL).length).toBeGreaterThanOrEqual(30);
        expect(GLSL['lib/glitch']).toContain('LYGIA');
        expect(GLSL['lib/glitch']).not.toContain('#include');
    });
    it('no allocation inside useFrame (zero per-frame garbage)', () => {
        const bad: string[] = [];
        for (const f of walk(HOLO).filter((x) => x.endsWith('.tsx') && !x.includes('.test.'))) {
            const src = readFileSync(f, 'utf8');
            for (const m of src.matchAll(/useFrame\(\s*\(([^)]*)\)\s*=>\s*\{/g)) {
                let depth = 1,
                    i = (m.index ?? 0) + m[0].length;
                const start = i;
                while (depth && i < src.length) {
                    if (src[i] === '{') depth++;
                    else if (src[i] === '}') depth--;
                    i++;
                }
                const body = src.slice(start, i);
                if (/\bnew [A-Z]\w*\(|\.clone\(\)|\[\.\.\.|\{\s*\.\.\./.test(body)) bad.push(f.replace(HOLO, ''));
            }
        }
        expect(bad).toEqual([]);
    });
});
