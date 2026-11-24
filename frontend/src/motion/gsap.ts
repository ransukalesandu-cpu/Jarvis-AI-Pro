// One GSAP setup for the whole UI (P5). Durations come from the tokens; easing is power2.out.
//   micro  120–180 ms  (hover, press)          -> DURATIONS['dur-fast']
//   transition 200–320 ms (panels, windows)    -> DURATIONS.dur
//   scene 600–1200 ms (stage changes)          -> DURATIONS['dur-scene']
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { DURATIONS } from '../styles/tokens';

// ScrollTrigger needs matchMedia at registration; test DOMs (jsdom) have none, and nothing scrolls there.
if (typeof window !== 'undefined' && typeof window.matchMedia === 'function') gsap.registerPlugin(ScrollTrigger);
gsap.defaults({ ease: 'power2.out', duration: DURATIONS.dur / 1000 });

export const EASE = 'power2.out';
export const sec = (name: keyof typeof DURATIONS) => DURATIONS[name] / 1000;

/** True when motion must not run: the owner's toggle, the OS setting, or no matchMedia (tests). */
export function motionOff(ownerReduced: boolean): boolean {
    if (ownerReduced) return true;
    if (typeof window === 'undefined' || typeof window.matchMedia !== 'function') return true;
    return window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

export { gsap, ScrollTrigger };
