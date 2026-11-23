import { describe, expect, it } from 'vitest';
import { visualLevel, visualState } from './visualState';
import { brainMood } from './brain/lobes';
import { eyeTarget } from './face/eyeStates';
import { COLORS, orbColor } from './palette';

describe('visualState', () => {
    it('shows offline whenever the backend link is down, whatever the last reported state', () => {
        for (const assistant of ['idle', 'speaking', 'thinking', 'listening'] as const)
            expect(visualState({ assistant, link: 'detached', muted: false })).toBe('offline');
    });
    it('never shows listening while the microphone is muted', () => {
        expect(visualState({ assistant: 'listening', link: 'connected', muted: true })).toBe('idle');
        expect(visualState({ assistant: 'listening', link: 'connected', muted: false })).toBe('listening');
    });
    it('passes every other real state through', () => {
        for (const assistant of ['idle', 'sleeping', 'thinking', 'searching', 'executing', 'speaking', 'warning', 'error'] as const)
            expect(visualState({ assistant, link: 'connected', muted: true })).toBe(assistant);
        expect(visualState({ assistant: 'thinking', link: 'connecting', muted: false })).toBe('thinking');
    });
    it('drives visuals with input level only while listening and output level only while speaking', () => {
        const lv = { inputLevel: 0.3, outputLevel: 0.8 };
        expect(visualLevel('listening', lv)).toBe(0.3);
        expect(visualLevel('speaking', lv)).toBe(0.8);
        expect(visualLevel('offline', lv)).toBe(0);
        expect(visualLevel('idle', lv)).toBe(0);
    });
});

describe('offline look', () => {
    it('is the calmest brain state and distinct from idle and sleeping', () => {
        const off = brainMood('offline'),
            idle = brainMood('idle'),
            sleep = brainMood('sleeping');
        expect(off.firing).toBeLessThan(sleep.firing);
        expect(off.flow).toBeLessThan(idle.flow);
        expect(off.tint).not.toEqual(idle.tint);
    });
    it('dims the eyes and turns the orb grey', () => {
        expect(eyeTarget('offline', 'L', 0).glow).toBeLessThan(eyeTarget('idle', 'L', 0).glow);
        expect(orbColor('offline').equals(COLORS.offline)).toBe(true);
        expect(orbColor('offline').equals(orbColor('idle'))).toBe(false);
    });
});
