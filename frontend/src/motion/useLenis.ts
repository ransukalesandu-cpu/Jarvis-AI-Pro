import { useEffect, type RefObject } from 'react';
import Lenis from 'lenis';
import { gsap, motionOff, ScrollTrigger } from './gsap';

/**
 * Smooth wheel scrolling inside a scroll container (window bodies), synced to GSAP's ticker so scroll and
 * animations share one frame clock. Off with reduced motion; keyboard and scrollbar scrolling stay native.
 */
export function useLenis(ref: RefObject<HTMLElement | null>, reduced: boolean) {
    useEffect(() => {
        const wrapper = ref.current;
        if (!wrapper || motionOff(reduced)) return;
        const content = (wrapper.firstElementChild as HTMLElement | null) ?? wrapper;
        const lenis = new Lenis({ wrapper, content, autoRaf: false, smoothWheel: true, lerp: 0.12 });
        lenis.on('scroll', ScrollTrigger.update);
        const tick = (t: number) => lenis.raf(t * 1000);
        gsap.ticker.add(tick);
        gsap.ticker.lagSmoothing(0);
        let alive = true;
        void document.fonts?.ready.then(() => alive && ScrollTrigger.refresh());
        return () => {
            alive = false;
            gsap.ticker.remove(tick);
            lenis.destroy();
        };
    }, [ref, reduced]);
}
