import { Component, Suspense, useCallback, useState, type ReactNode } from 'react';
import { RotateCcw, TriangleAlert } from 'lucide-react';

/** Why the 3D stage is not drawing. Shown to the user: the stage is never left silently blank. */
export type RendererProblem = 'no-webgl2' | 'context-lost' | 'crashed';

export const PROBLEM_TEXT: Record<RendererProblem, { title: string; detail: string; canRetry: boolean }> = {
    'no-webgl2': {
        title: '3D hologram unavailable',
        detail: 'This display engine has no WebGL 2 (GPU acceleration may be off). JARVIS keeps working; inside the desktop app the classic HUD takes over.',
        canRetry: false,
    },
    'context-lost': {
        title: 'Graphics renderer was reset',
        detail: 'The GPU dropped the 3D context (driver reset, sleep or low memory). Voice and commands are not affected.',
        canRetry: true,
    },
    crashed: {
        title: 'Hologram renderer stopped',
        detail: 'The 3D scene hit an error and was stopped so the rest of the interface stays usable.',
        canRetry: true,
    },
};

export function RendererNotice({ problem, onRetry }: { problem: RendererProblem; onRetry?: () => void }) {
    const t = PROBLEM_TEXT[problem];
    return (
        <div className="renderer-notice glass" role="alert" data-problem={problem}>
            <TriangleAlert size={16} aria-hidden />
            <div>
                <strong>{t.title}</strong>
                <p>{t.detail}</p>
                {t.canRetry && onRetry && (
                    <button className="toggle" onClick={onRetry}>
                        <RotateCcw size={13} aria-hidden /> Restart renderer
                    </button>
                )}
            </div>
        </div>
    );
}

class Boundary extends Component<{ onCrash: () => void; children: ReactNode }, { failed: boolean }> {
    state = { failed: false };
    static getDerivedStateFromError() {
        return { failed: true };
    }
    componentDidCatch() {
        this.props.onCrash();
    }
    render() {
        return this.state.failed ? null : this.props.children;
    }
}

/**
 * Hosts the 3D scene. Handles the three ways it can fail (no WebGL 2, GPU context lost, a throw in the
 * scene) with a visible notice, and lets the user restart the renderer: a new key remounts the canvas,
 * whose old WebGL resources React Three Fiber disposes on unmount.
 */
export function RendererGuard({ webgl2, scene }: { webgl2: boolean; scene: (onLost: () => void) => ReactNode }) {
    const [problem, setProblem] = useState<RendererProblem | null>(webgl2 ? null : 'no-webgl2');
    const [gen, setGen] = useState(0);
    const lost = useCallback(() => setProblem('context-lost'), []);
    const crash = useCallback(() => setProblem('crashed'), []);
    const retry = useCallback(() => {
        setProblem(null);
        setGen((g) => g + 1);
    }, []);
    if (problem) return <RendererNotice problem={problem} onRetry={retry} />;
    return (
        <Boundary key={gen} onCrash={crash}>
            <Suspense fallback={null}>{scene(lost)}</Suspense>
        </Boundary>
    );
}
