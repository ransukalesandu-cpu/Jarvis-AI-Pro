import { describe, expect, it } from 'vitest';
import { ASKS } from './Palette';

describe('palette asks', () => {
  it('are the fixed phrases the native menu uses, short and credential-free', () => {
    expect(ASKS.map((a) => a.text)).toEqual(['show my routines', 'list my background jobs', 'show recent actions']);
    for (const a of ASKS) expect(a.text).not.toMatch(/owner|pin|login|password/i);
  });
});
