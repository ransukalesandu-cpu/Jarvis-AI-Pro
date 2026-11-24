import { lazy, Suspense } from 'react';
import { AdaptiveDpr, Preload } from '@react-three/drei';
import { useUi } from '../../store';

// Development tools (npm run dev only; production builds drop both imports):
//   r3f-perf — GPU/CPU timing HUD, shown with the Performance overlay. It takes over renderer.info, so it
//              must not run where the overlay's own draw-call numbers are measured (check_budget.py: ?budget).
//   Leva     — live stage knobs.
const devTools = import.meta.env.DEV && !(typeof location !== 'undefined' && location.search.includes('budget'));
const Perf = devTools ? lazy(() => import('r3f-perf').then((m) => ({ default: m.Perf }))) : null;
const StageTweaks = devTools ? lazy(() => import('./StageTweaks')) : null;

/**
 * Scene helpers (drei): compile every material before the first frame (no first-use hitch), and lower the
 * pixel ratio while the frame rate drops (pixelated, so it stays crisp), restoring it when it recovers.
 */
export function StageExtras() {
    const perfOverlay = useUi((s) => s.perfOverlay);
    return (
        <>
            <Preload all />
            <AdaptiveDpr pixelated />
            <Suspense fallback={null}>
                {Perf && perfOverlay && <Perf position="bottom-left" minimal />}
                {StageTweaks && <StageTweaks />}
            </Suspense>
        </>
    );
}
