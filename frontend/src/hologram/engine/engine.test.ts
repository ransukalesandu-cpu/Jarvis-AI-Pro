import { beforeEach, describe, expect, it } from 'vitest';
import { encodeRequest } from '../../bridge/contract';
import { hasWebGL2, resetCapability } from './capability';
import { QUALITY, qualityFor } from './quality';

const canvas = (ctx: unknown) => (() => ({ getContext: () => ctx }) as unknown as HTMLCanvasElement);

describe('WebGL2 capability probe', () => {
  beforeEach(() => resetCapability());
  it('is true with a webgl2 context and frees the probe context', () => {
    let lost = false;
    const gl = { getExtension: () => ({ loseContext: () => { lost = true; } }) };
    expect(hasWebGL2(canvas(gl))).toBe(true);
    expect(lost).toBe(true);
  });
  it('is false without one, or when the canvas throws, and is cached', () => {
    expect(hasWebGL2(canvas(null))).toBe(false);
    expect(hasWebGL2(canvas({ getExtension: () => null }))).toBe(false);   // cached from the first probe
    resetCapability();
    expect(hasWebGL2(() => { throw new Error('no canvas'); })).toBe(false);
  });
  it('is reported to Python in the request shape the host accepts', () => {
    expect(encodeRequest({ kind: 'hologram.capability', webgl2: false })).toBe('{"kind":"hologram.capability","webgl2":false}');
  });
});

describe('quality profiles follow the host tier', () => {
  it('maps full / balanced / lite and defaults to balanced', () => {
    expect(qualityFor('full').dpr).toEqual([1, 2]);
    expect(qualityFor('lite')).toMatchObject({ dpr: 1, fpsCap: 30, backdropHalo: false, dust: false });
    expect(qualityFor(null)).toBe(QUALITY.balanced);
    expect(QUALITY.balanced.fpsCap).toBeNull();
  });
});
