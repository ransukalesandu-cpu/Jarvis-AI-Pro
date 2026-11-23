// Small colour maths for the token build (no extra dependency): parse hex / rgb[a](), sRGB -> OKLCH, Qt forms.
export function parseColor(value) {
    const v = String(value).trim();
    let m = /^#([0-9a-f]{3,8})$/i.exec(v);
    if (m) {
        let h = m[1];
        if (h.length <= 4) h = [...h].map((c) => c + c).join('');
        const n = (i) => parseInt(h.slice(i, i + 2), 16);
        return { r: n(0), g: n(2), b: n(4), a: h.length === 8 ? n(6) / 255 : 1 };
    }
    m = /^rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)$/i.exec(v);
    if (m) return { r: +m[1], g: +m[2], b: +m[3], a: m[4] === undefined ? 1 : +m[4] };
    throw new Error(`unsupported colour: ${value}`);
}

const lin = (c) => {
    c /= 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
};

export function oklch({ r, g, b }) {
    const [R, G, B] = [lin(r), lin(g), lin(b)];
    const l = Math.cbrt(0.4122214708 * R + 0.5363325363 * G + 0.0514459929 * B);
    const m = Math.cbrt(0.2119034982 * R + 0.6806995451 * G + 0.1073969566 * B);
    const s = Math.cbrt(0.0883024619 * R + 0.2817188376 * G + 0.6299787005 * B);
    const L = 0.2104542553 * l + 0.793617785 * m - 0.0040720468 * s;
    const A = 1.9779984951 * l - 2.428592205 * m + 0.4505937099 * s;
    const Bb = 0.0259040371 * l + 0.7827717662 * m - 0.808675766 * s;
    const C = Math.sqrt(A * A + Bb * Bb);
    let H = (Math.atan2(Bb, A) * 180) / Math.PI;
    if (H < 0) H += 360;
    return { L, C, H: C < 1e-4 ? 0 : H };
}

export function toOklch(value) {
    const c = parseColor(value);
    const { L, C, H } = oklch(c);
    const body = `${(L * 100).toFixed(2)}% ${C.toFixed(4)} ${H.toFixed(2)}`;
    return c.a < 1 ? `oklch(${body} / ${+c.a.toFixed(3)})` : `oklch(${body})`;
}

export function toQss(value) {
    const c = parseColor(value);
    if (c.a >= 1) return '#' + [c.r, c.g, c.b].map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
    return `rgba(${c.r}, ${c.g}, ${c.b}, ${Math.round(c.a * 255)})`;
}

export const toHexNumber = (c) => '0x' + [c.r, c.g, c.b].map((x) => Math.round(x).toString(16).padStart(2, '0')).join('');
