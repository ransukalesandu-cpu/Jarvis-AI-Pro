import { describe, expect, it } from 'vitest';
import { en } from './en';
import { si } from './si';
import { translate } from '.';

const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).sort();

describe('UI strings (English / සිංහල)', () => {
    it('both catalogs have exactly the same keys and no empty text', () => {
        expect(Object.keys(si).sort()).toEqual(Object.keys(en).sort());
        expect(Object.entries(si).filter(([, v]) => !v.trim())).toEqual([]);
    });
    it('placeholders match so no value is lost in translation', () => {
        const mismatched = (Object.keys(en) as (keyof typeof en)[]).filter((k) => placeholders(si[k]).join() !== placeholders(en[k]).join());
        expect(mismatched).toEqual([]);
    });
    it('Sinhala strings are written in Sinhala script (technical names may stay English)', () => {
        const sinhala = /[඀-෿]/;
        const allowedLatinOnly = new Set(['set.ai', 'models.key']);
        const latin = Object.entries(si).filter(([k, v]) => !allowedLatinOnly.has(k) && !sinhala.test(v));
        expect(latin).toEqual([]);
    });
    it('fills placeholders and falls back to English, never to the key', () => {
        expect(translate('si', 's.loading', { what: 'X' })).toBe('X පූරණය වෙමින්');
        expect(translate('en', 'result.too_long', { max: 400 })).toBe('Too long (max 400)');
    });
});
