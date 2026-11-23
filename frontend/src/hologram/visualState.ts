/**
 * What the hologram should *show*, derived from real backend state only.
 *
 * - offline: the backend link is down (detached). The page never pretends JARVIS is working.
 * - a 'listening' report while the microphone is muted is shown as idle: the hologram must never
 *   suggest it is listening when the mic is off.
 * Everything else passes through unchanged. Pure, so it is unit-tested.
 */
import type { AssistantState } from '../bridge/contract';

export type VisualState = AssistantState | 'offline';

export interface VisualInputs {
    assistant: AssistantState;
    link: 'connecting' | 'connected' | 'detached';
    muted: boolean;
}

export function visualState(s: VisualInputs): VisualState {
    if (s.link === 'detached') return 'offline';
    if (s.assistant === 'listening' && s.muted) return 'idle';
    return s.assistant;
}

/** The audio level that should drive the visuals in this state (input while listening, output while speaking). */
export function visualLevel(state: VisualState, s: { inputLevel: number; outputLevel: number }): number {
    return state === 'speaking' ? s.outputLevel : state === 'listening' ? s.inputLevel : 0;
}
