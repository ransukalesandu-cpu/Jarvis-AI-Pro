// Token gate (UI P1): component CSS/TSX may not carry colour, font-size, radius or duration literals.
// Raw values live only in tokens/core.json; src/styles/tokens.css and tokens.ts are generated from it.
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';
import { STAGE_TOKENS } from './tokens';

const SRC = join(__dirname, '..');
const walk = (dir: string): string[] =>
    readdirSync(dir).flatMap((n) => {
        const p = join(dir, n);
        return statSync(p).isDirectory() ? walk(p) : [p];
    });
const COLOR = /#[0-9a-fA-F]{3,8}\b|rgba?\(|oklch\(|hsla?\(/;
const GENERATED = /tokens\.(css|ts)$/;

describe('design tokens', () => {
    const css = walk(join(SRC, 'styles')).filter((f) => f.endsWith('.css') && !GENERATED.test(f));
    it.each(css)('%s has no colour, font-size, radius or duration literals', (f) => {
        const bad = readFileSync(f, 'utf8')
            .split('\n')
            .filter(
                (l) =>
                    COLOR.test(l) ||
                    /:root\s*\{/.test(l) ||
                    /font(-size)?:[^;]*\b[\d.]+px/.test(l) ||
                    /^\s*(padding|margin|gap|row-gap|column-gap)[a-z-]*:[^;]*\b[\d.]*[1-9]px/.test(l) ||
                    /shadow:[^;]*\d+px/.test(l) ||
                    /border-radius:[^;]*\d+(px|%)/.test(l) ||
                    /(transition|animation)[^;]*\b\d+m?s\b/.test(l),
            );
        expect(bad).toEqual([]);
    });
    it('component TSX outside the 3D stage has no colour literals', () => {
        const tsx = walk(SRC).filter((f) => f.endsWith('.tsx') && !f.includes('hologram') && !f.includes('.test.'));
        const bad = tsx.filter((f) => /['"`]#[0-9a-fA-F]{3,8}['"`]|['"]rgba?\(/.test(readFileSync(f, 'utf8')));
        expect(bad).toEqual([]);
    });

    it('3D stage code takes its colours from the tokens (stageColor), not literals', () => {
        const files = walk(join(SRC, 'hologram')).filter((f) => /\.(ts|tsx)$/.test(f) && !f.includes('.test.'));
        const bad = files.filter((f) => /['"`]#[0-9a-fA-F]{6}['"`]|\b0x[0-9a-fA-F]{6}\b/.test(readFileSync(f, 'utf8')));
        expect(bad).toEqual([]);
    });

    const lum = (hex: number) => {
        const c = [16, 8, 0].map((s) => ((hex >> s) & 255) / 255).map((x) => (x <= 0.03928 ? x / 12.92 : ((x + 0.055) / 1.055) ** 2.4));
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
    };
    const ratio = (a: number, b: number) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
    // Text sits on glass over the backdrop; the backdrop colour is the worst case for each theme.
    it.each(['dark', 'light', 'hc'] as const)('%s theme: body text 4.5:1, UI colours 3:1', (theme) => {
        const t = STAGE_TOKENS[theme];
        const surface = theme === 'light' ? 0xffffff : t.bg.hex;
        for (const name of ['text', 'text-dim', 'text-faint'] as const) expect(ratio(t[name].hex, surface)).toBeGreaterThanOrEqual(4.5);
        for (const name of ['primary', 'ok', 'warn', 'danger'] as const) expect(ratio(t[name].hex, surface)).toBeGreaterThanOrEqual(3);
    });
});
