/** Loading UX rules, in one place so they are the same everywhere and easy to test:
 *   under 1 s      -> show nothing (a flash of spinner is worse than none)
 *   1 s to 10 s    -> a skeleton of what is coming
 *   over 10 s      -> progress and time left (an estimate, labelled as one)
 */
export const SHOW_AFTER_MS = 1000;
export const PROGRESS_AFTER_MS = 10_000;
export const EXPIRE_MS = 60_000;     // an operation that never answers is dropped, with a notice

export type Phase = 'none' | 'skeleton' | 'progress';

export function phaseFor(elapsedMs: number): Phase {
  if (!(elapsedMs >= SHOW_AFTER_MS)) return 'none';
  return elapsedMs >= PROGRESS_AFTER_MS ? 'progress' : 'skeleton';
}

/** What we typically expect each kind of operation to take, until we have learned the real figure. */
const DEFAULT_EXPECTED_MS: Record<string, number> = {
  startup: 6000, 'workspace.load': 2000, 'workspace.save': 1500, 'workspace.delete': 1500, command: 3000, control: 1000, mute: 1500,
};

/** Learns how long each kind of operation really takes (exponential moving average), so "time left" improves with use. */
export class DurationModel {
  private ema = new Map<string, number>();
  constructor(private alpha = 0.3) {}
  record(kind: string, ms: number): void {
    if (!(ms >= 0) || !Number.isFinite(ms)) return;
    const prev = this.ema.get(kind);
    this.ema.set(kind, prev === undefined ? ms : prev + this.alpha * (ms - prev));
  }
  expected(kind: string): number { return this.ema.get(kind) ?? DEFAULT_EXPECTED_MS[kind] ?? 5000; }
}

export interface Estimate { fraction: number; remainingMs: number }

/** Honest estimate: never reaches 100 % before the operation actually finishes, and when it overruns the guess grows with it. */
export function estimate(elapsedMs: number, expectedMs: number): Estimate {
  const total = Math.max(expectedMs, elapsedMs * 1.25, SHOW_AFTER_MS);
  return { fraction: Math.min(0.95, elapsedMs / total), remainingMs: Math.max(1000, total - elapsedMs) };
}

export function formatRemaining(ms: number): string {
  const s = Math.max(1, Math.round(ms / 1000));
  if (s < 5) return 'a few seconds left';
  if (s < 90) return `about ${s < 20 ? s : Math.round(s / 5) * 5} s left`;
  return `about ${Math.round(s / 60)} min left`;
}
