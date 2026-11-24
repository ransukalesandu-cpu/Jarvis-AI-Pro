import { Canvas, useThree } from '@react-three/fiber';
import { useEffect, useLayoutEffect, useState } from 'react';
import { useUi } from '../store';
import { PerfGovernor } from './engine/PerfGovernor';
import { qualityFor } from './engine/quality';
import { Head } from './Head';
import { MechanicalHead } from './face/MechanicalHead';
import { NeuralBrain } from './brain/NeuralBrain';
import { Arcs, Backdrop, LAYOUT, Orb, Particles, Strands } from './Stage';
import { stageHex } from './stageColor';
import { StageExtras } from './engine/StageExtras';

const FOV = 28;
/** The prompt's budget: pixel ratio between 1 and 1.5 (sharper screens are not worth the fill cost here). */
export const clampDpr = (d: number | [number, number]): [number, number] => {
    const [lo, hi] = Array.isArray(d) ? d : [d, d];
    return [Math.max(1, Math.min(lo, 1.5)), Math.max(1, Math.min(hi, 1.5))];
};
const BOUNDS = { halfWidth: 2.2, top: 1.7, bottom: -2.3 }; // room under the orb for the command bar

/** Contain the whole composition (face, strands, orb) in any window size. */
function FitCamera() {
    const { camera, size } = useThree();
    useLayoutEffect(() => {
        const aspect = size.width / Math.max(1, size.height);
        const h = BOUNDS.top - BOUNDS.bottom,
            cy = (BOUNDS.top + BOUNDS.bottom) / 2;
        const t = Math.tan((FOV * Math.PI) / 360);
        const dist = Math.max(h / 2 / t, BOUNDS.halfWidth / aspect / t) * 1.04;
        camera.position.set(0, cy, dist);
        camera.lookAt(0, cy, 0);
        camera.updateProjectionMatrix();
    }, [camera, size]);
    return null;
}

/** Caps the frame rate (Eco): render on demand and ask for a frame at the cap. */
function FrameCap({ fps }: { fps: number }) {
    const invalidate = useThree((s) => s.invalidate);
    useEffect(() => {
        const id = setInterval(() => invalidate(), 1000 / fps);
        return () => clearInterval(id);
    }, [fps, invalidate]);
    return null;
}

/** True while the page is hidden (window minimised or covered by another tab/app): nothing is drawn then. */
function usePageHidden(): boolean {
    const [hidden, setHidden] = useState(() => typeof document !== 'undefined' && document.hidden);
    useEffect(() => {
        const on = () => setHidden(document.hidden);
        document.addEventListener('visibilitychange', on);
        return () => document.removeEventListener('visibilitychange', on);
    }, []);
    return hidden;
}

export function stageLabel(centre: 'brain' | 'hologram', face: 'circuit' | 'mechanical', state: string): string {
    const figure = centre === 'brain' ? 'a living neural brain' : face === 'mechanical' ? 'a mechanical hologram head' : 'a circuit hologram head';
    return `JARVIS hologram: ${figure} above a glowing orb. JARVIS is ${state}.`;
}

export function HologramScene({ onContextLost }: { onContextLost?: () => void } = {}) {
    const q = qualityFor(useUi((s) => s.perfTier));
    const hidden = usePageHidden();
    const faceStyle = useUi((s) => s.faceStyle);
    const centerStyle = useUi((s) => s.centerStyle);
    const frameloop = hidden ? 'never' : q.fpsCap ? 'demand' : 'always';
    const assistant = useUi((s) => s.assistant);
    return (
        // The canvas is a picture of JARVIS's state: one text alternative here, the pixels stay hidden from AT.
        <div className="stage-canvas" role="img" aria-label={stageLabel(centerStyle, faceStyle, assistant)}>
            <Canvas
                camera={{ fov: FOV, near: 0.1, far: 50, position: [0, 0, 10] }}
                gl={{ alpha: true, antialias: true, powerPreference: 'high-performance', precision: 'highp' }}
                dpr={clampDpr(q.dpr)}
                aria-hidden
                fallback={<p className="stage-fallback">The 3D hologram needs WebGL 2, which this display does not offer.</p>}
                frameloop={frameloop}
                onCreated={({ gl }) => {
                    gl.setClearColor(stageHex('stage-black'), 0);
                    // A lost GPU context would otherwise leave a frozen or blank stage: report it so a notice and a restart show.
                    gl.domElement.addEventListener(
                        'webglcontextlost',
                        (e) => {
                            e.preventDefault();
                            onContextLost?.();
                        },
                        { once: true },
                    );
                }}
            >
                <FitCamera />
                <StageExtras />
                <PerfGovernor quality={q} />
                {q.fpsCap && !hidden && <FrameCap fps={q.fpsCap} />}
                <Backdrop halo={q.backdropHalo} dust={q.dust} />
                {centerStyle === 'brain' ? (
                    <NeuralBrain nodes={q.brainNodes} />
                ) : (
                    <group position={[LAYOUT.head.x, LAYOUT.head.y, 0]} scale={0.95}>
                        {faceStyle === 'mechanical' ? <MechanicalHead /> : <Head />}
                    </group>
                )}
                {/* With the brain, its own neurons reach the orb; the strands and arcs belong to the head. */}
                {centerStyle !== 'brain' && <Strands />}
                <Particles count={q.particles} />
                {centerStyle !== 'brain' && <Arcs count={q.arcs} />}
                <Orb />
            </Canvas>
        </div>
    );
}
