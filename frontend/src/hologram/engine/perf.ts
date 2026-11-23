import { create } from 'zustand';

/** Live render numbers (measured in the page) and the host's numbers for the web engine process. */
export interface PagePerf {
    fps: number;
    frameMs: number;
    drawCalls: number;
    triangles: number;
    heapMb: number | null;
    dpr: number;
}
export interface HostPerf {
    cpu: number;
    ramMb: number;
    processes: number;
}

interface PerfState {
    page: PagePerf | null;
    host: HostPerf | null;
    setPage: (p: PagePerf) => void;
    setHost: (h: HostPerf) => void;
}

export const usePerf = create<PerfState>((set) => ({
    page: null,
    host: null,
    setPage: (page) => set({ page }),
    setHost: (host) => set({ host }),
}));

/** JS heap in MB where the engine exposes it (Chromium / QtWebEngine), else null. Never estimated. */
export function heapMb(): number | null {
    const m = (performance as unknown as { memory?: { usedJSHeapSize?: number } }).memory;
    return m && typeof m.usedJSHeapSize === 'number' ? Math.round(m.usedJSHeapSize / 1048576) : null;
}
