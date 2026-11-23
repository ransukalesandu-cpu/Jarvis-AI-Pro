import { useFrame } from '@react-three/fiber';
import { useEffect, useMemo, useRef } from 'react';
import { AdditiveBlending, Color, type Group, type Mesh } from 'three';
import { useUi } from '../../store';
import { glassMaterial } from '../glass';
import { COLORS, orbColor } from '../palette';
import { plasmaMaterial } from './plasma';
import { LAYOUT } from './paths';
import { busyState } from './Strands';
import { visualState } from '../visualState';

const add = (color: Color, opacity: number) => ({ color, transparent: true, opacity, blending: AdditiveBlending, depthWrite: false }) as const;

/** Orb v2: a glass shell, a turning plasma core (GPU noise), latitude net, bright centre, tilted orbit rings and two platform rings below. */
export function Orb() {
    const shell = useRef<Mesh>(null);
    const net = useRef<Mesh>(null);
    const core = useRef<Mesh>(null);
    const halo = useRef<Mesh>(null);
    const rings = useRef<Group>(null);
    const plates = useRef<Group>(null);
    const glass = useMemo(() => glassMaterial(COLORS.orb, COLORS.orbBody, { bodyAlpha: 0.08, power: 1.8, displace: 0.004 }), []);
    const plasma = useMemo(() => plasmaMaterial(COLORS.orb), []);
    useEffect(
        () => () => {
            glass.dispose();
            plasma.dispose();
        },
        [glass, plasma],
    );
    const col = useMemo(() => new Color(COLORS.orb), []);
    useFrame((s, dt) => {
        const ui = useUi.getState(),
            t = s.clock.elapsedTime,
            red = ui.reducedMotion ? 0.3 : 1;
        const vs = visualState(ui); // real state only: 'offline' when the backend link is down, never 'listening' with the mic muted
        col.lerp(orbColor(vs), Math.min(1, dt * 4));
        const level = vs === 'speaking' ? ui.outputLevel : vs === 'listening' ? ui.inputLevel : 0;
        const busy = busyState(vs);
        glass.uniforms.rim.value.copy(col);
        glass.uniforms.boost.value = level * 0.5;
        glass.uniforms.time.value = t * red;
        plasma.uniforms.time.value = t * red * (busy ? 2 : 1);
        plasma.uniforms.color.value.copy(col);
        plasma.uniforms.energy.value = 0.35 + level * 0.65 + (busy ? 0.25 : 0);
        const breathe = 1 + 0.04 * Math.sin(t * 1.4) * red + level * 0.25;
        core.current?.scale.setScalar(breathe);
        halo.current?.scale.setScalar(1 + level * 0.5 + 0.05 * Math.sin(t * 1.1) * red);
        if (net.current) net.current.rotation.y += dt * 0.25 * red;
        const spin = (busy ? 1.8 : 0.35) * red;
        rings.current?.children.forEach((m, i) => {
            m.rotation.z += dt * spin * (i % 2 ? -1 : 1) * (0.6 + i * 0.25);
            ((m as Mesh).material as unknown as { color: Color }).color.copy(col);
        });
        plates.current?.children.forEach((m, i) => {
            m.rotation.z += dt * 0.2 * red * (i % 2 ? -1 : 1);
        });
        for (const m of [halo.current, net.current]) if (m) (m.material as unknown as { color: Color }).color.copy(col);
    });
    const { x, y, r } = LAYOUT.orb;
    return (
        <group position={[x, y, 0.1]}>
            <mesh ref={halo}>
                <circleGeometry args={[r * 2.2, 48]} />
                <meshBasicMaterial {...add(COLORS.orb, 0.025)} />
            </mesh>
            <mesh ref={shell} material={glass}>
                <sphereGeometry args={[r, 48, 32]} />
            </mesh>
            <mesh ref={net}>
                <sphereGeometry args={[r * 0.99, 18, 12]} />
                <meshBasicMaterial {...add(COLORS.orb, 0.12)} wireframe />
            </mesh>
            <mesh material={plasma}>
                <sphereGeometry args={[r * 0.62, 40, 28]} />
            </mesh>
            <mesh ref={core}>
                <sphereGeometry args={[r * 0.2, 24, 16]} />
                <meshBasicMaterial {...add(COLORS.orbCore, 0.95)} />
            </mesh>
            <group ref={rings}>
                {[
                    [1.25, 1.2, 0.012],
                    [1.5, 1.38, 0.008],
                    [1.8, 1.5, 0.006],
                ].map(([s, tilt, w], i) => (
                    <mesh key={i} rotation={[tilt, 0, i * 0.7]}>
                        <torusGeometry args={[r * s, w, 8, 128]} />
                        <meshBasicMaterial {...add(COLORS.orb, 0.75 - i * 0.18)} />
                    </mesh>
                ))}
            </group>
            <group ref={plates} position={[0, -r * 0.95, 0]}>
                {[
                    [1.6, 0.01, 0.6],
                    [2.3, 0.007, 0.35],
                    [3.0, 0.005, 0.2],
                ].map(([s, w, o], i) => (
                    <mesh key={i} rotation={[Math.PI / 2 - 0.12, 0, 0]}>
                        <torusGeometry args={[r * s, w, 6, 128]} />
                        <meshBasicMaterial {...add(COLORS.ring, o)} />
                    </mesh>
                ))}
            </group>
        </group>
    );
}
