import { useEffect, useLayoutEffect, useRef, useState, type ReactElement, type RefObject } from 'react';
import { gsap, motionOff, sec } from './gsap';

export interface PresenceProps<T extends HTMLElement> {
    show: boolean;
    /** Where the element comes from / goes to, e.g. { x: -24 } or { y: 14, scale: 0.97 }. Opacity is always faded. */
    offset: gsap.TweenVars;
    /** The owner's Reduced motion setting (the OS setting is checked too, via gsap.matchMedia). */
    reduced: boolean;
    children: (ref: RefObject<T | null>) => ReactElement;
}

/**
 * Mount/unmount with an enter and exit animation (replaces Motion's AnimatePresence).
 * Purpose: orientation — panels slide from the side they belong to. Timelines are killed on unmount
 * (gsap.context revert); with reduced motion the element simply appears and disappears.
 */
export function Presence<T extends HTMLElement>({ show, offset, reduced, children }: PresenceProps<T>) {
    const [mounted, setMounted] = useState(show);
    const ref = useRef<T | null>(null);
    const off = motionOff(reduced);

    useEffect(() => {
        if (show) setMounted(true);
        else if (off) setMounted(false);
    }, [show, off]);

    useLayoutEffect(() => {
        const el = ref.current;
        if (!el || !mounted || off) return;
        const mm = gsap.matchMedia();
        mm.add({ motion: '(prefers-reduced-motion: no-preference)', still: '(prefers-reduced-motion: reduce)' }, (ctx) => {
            const still = Boolean(ctx.conditions?.still);
            if (show) {
                gsap.fromTo(el, { ...(still ? {} : offset), opacity: 0 }, { x: 0, y: 0, scale: 1, opacity: 1, duration: still ? 0 : sec('dur') });
            } else {
                gsap.to(el, {
                    ...(still ? {} : offset),
                    opacity: 0,
                    duration: still ? 0 : sec('dur-fast'),
                    ease: 'power2.in',
                    onComplete: () => setMounted(false),
                });
            }
        });
        return () => mm.revert();
        // offset is a literal from the caller; re-running on its identity would restart the animation.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [show, mounted, off]);

    return mounted ? children(ref) : null;
}
