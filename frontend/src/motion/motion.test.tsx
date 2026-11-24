import { act, useState } from 'react';
import { createRoot, type Root } from 'react-dom/client';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { afterEach, describe, expect, it } from 'vitest';
import { Presence } from './Presence';
import { motionOff } from './gsap';

(globalThis as { IS_REACT_ACT_ENVIRONMENT?: boolean }).IS_REACT_ACT_ENVIRONMENT = true;
let root: Root | null = null;
afterEach(() => {
    act(() => root?.unmount());
    root = null;
});

describe('motion policy', () => {
    it('one animation library: GSAP only (Motion / Framer Motion are banned)', () => {
        const pkg = JSON.parse(readFileSync(join(__dirname, '..', '..', 'package.json'), 'utf8'));
        const deps = { ...pkg.dependencies, ...pkg.devDependencies };
        expect(deps.gsap).toBeTruthy();
        expect(deps.motion).toBeUndefined();
        expect(deps['framer-motion']).toBeUndefined();
    });
    it('reduced motion: the owner setting or no matchMedia turns animation off', () => {
        expect(motionOff(true)).toBe(true);
        expect(motionOff(false)).toBe(typeof window.matchMedia !== 'function' || window.matchMedia('(prefers-reduced-motion: reduce)').matches);
    });
});

describe('Presence', () => {
    it('mounts and unmounts immediately when motion is off', () => {
        const host = document.createElement('div');
        let set: (v: boolean) => void = () => {};
        function T() {
            const [show, setShow] = useState(false);
            set = setShow;
            return (
                <Presence<HTMLDivElement> show={show} reduced offset={{ x: -24 }}>
                    {(ref) => (
                        <div ref={ref} id="panel">
                            hi
                        </div>
                    )}
                </Presence>
            );
        }
        root = createRoot(host);
        act(() => root!.render(<T />));
        expect(host.querySelector('#panel')).toBeNull();
        act(() => set(true));
        expect(host.querySelector('#panel')).not.toBeNull();
        act(() => set(false));
        expect(host.querySelector('#panel')).toBeNull();
    });
});
