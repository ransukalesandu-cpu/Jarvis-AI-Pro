import { useCallback } from 'react';
import { useUi } from '../store';
import { en, type StringKey } from './en';
import { si } from './si';

export const LANGS = ['en', 'si'] as const;
export type Lang = (typeof LANGS)[number];
export const LANG_NAMES: Record<Lang, string> = { en: 'English', si: 'සිංහල' };
const CATALOG: Record<Lang, Record<StringKey, string>> = { en, si };

/** A UI string in ``lang``; {placeholders} filled from ``vars``. Falls back to English, never to the key. */
export function translate(lang: Lang, key: StringKey, vars?: Record<string, string | number>): string {
    const raw = CATALOG[lang]?.[key] ?? en[key];
    return vars ? raw.replace(/\{(\w+)\}/g, (_, k: string) => String(vars[k] ?? `{${k}}`)) : raw;
}

/** Translator bound to the current UI language (re-renders when the owner switches it). */
export function useT() {
    const lang = useUi((s) => s.lang);
    return useCallback((key: StringKey, vars?: Record<string, string | number>) => translate(lang, key, vars), [lang]);
}

/** For code outside React (constants, tests): the language right now. */
export const t = (key: StringKey, vars?: Record<string, string | number>) => translate(useUi.getState().lang, key, vars);

export type { StringKey };
