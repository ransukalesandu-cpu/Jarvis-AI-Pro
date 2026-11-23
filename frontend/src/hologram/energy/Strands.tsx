import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo } from 'react';
import { BufferGeometry, Float32BufferAttribute } from 'three';
import { useUi } from '../../store';
import { COLORS } from '../palette';
import { flowLineMaterial } from './flowLines';
import { strandSegments } from './paths';
import { visualState } from '../visualState';

export const busyState = (s: string): boolean => s === 'speaking' || s === 'thinking' || s === 'executing' || s === 'searching';

/** Energy strands from the neck into the orb, all in one draw; light runs down them on the GPU. */
export function Strands() {
    const { geo, mat } = useMemo(() => {
        const s = strandSegments();
        const geo = new BufferGeometry();
        geo.setAttribute('position', new Float32BufferAttribute(s.position, 3));
        geo.setAttribute('along', new Float32BufferAttribute(s.along, 1));
        geo.setAttribute('seed', new Float32BufferAttribute(s.seed, 1));
        return { geo, mat: flowLineMaterial(COLORS.wire, COLORS.orbCore) };
    }, []);
    useEffect(
        () => () => {
            geo.dispose();
            mat.dispose();
        },
        [geo, mat],
    );
    useFrame((s, dt) => {
        const ui = useUi.getState(),
            red = ui.reducedMotion ? 0.3 : 1;
        const vs = visualState(ui); // real state only: 'offline' when the backend link is down, never 'listening' with the mic muted
        const busy = busyState(vs);
        const u = mat.uniforms;
        u.time.value += dt * red;
        u.speed.value += ((busy ? 0.5 : 0.15) - u.speed.value) * Math.min(1, dt * 3);
        u.base.value += ((busy ? 0.42 : 0.24) - u.base.value) * Math.min(1, dt * 3);
        u.gain.value = busy ? 0.95 : 0.5;
        void s;
    });
    return <lineSegments geometry={geo} material={mat} />;
}
