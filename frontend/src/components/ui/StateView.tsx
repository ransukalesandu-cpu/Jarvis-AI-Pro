import type { ReactNode } from 'react';
import { CircleCheck, CloudOff, Inbox, TriangleAlert } from 'lucide-react';
import { Button } from './Button';

export type ViewState = 'loading' | 'empty' | 'error' | 'offline' | 'success';

export interface StateViewProps {
    kind: ViewState;
    title: string;
    message?: ReactNode;
    /** Error: shows "Try again". Offline/empty: an optional next step. */
    onRetry?: () => void;
    retryLabel?: string;
    action?: ReactNode;
    /** Skeleton lines while loading (default 3). */
    lines?: number;
}

const ICON = { empty: Inbox, error: TriangleAlert, offline: CloudOff, success: CircleCheck } as const;

/** One look for every window's non-data states: loading (skeleton), empty, error (+ retry), offline and success. */
export function StateView({ kind, title, message, onRetry, retryLabel = 'Try again', action, lines = 3 }: StateViewProps) {
    if (kind === 'loading') {
        return (
            <div className="ui-state" data-kind="loading" role="status" aria-busy="true" aria-label={title}>
                {Array.from({ length: lines }, (_, i) => (
                    <span key={i} className="ui-skeleton" data-line={i} />
                ))}
            </div>
        );
    }
    const Icon = ICON[kind];
    return (
        <div className="ui-state" data-kind={kind} role={kind === 'error' ? 'alert' : 'status'}>
            <Icon size={20} aria-hidden className="ui-state-icon" />
            <p className="ui-state-title">{title}</p>
            {message && <p className="ui-hint">{message}</p>}
            {(onRetry || action) && (
                <div className="ui-state-actions">
                    {onRetry && (
                        <Button size="sm" variant="outline" tone="neutral" onClick={onRetry}>
                            {retryLabel}
                        </Button>
                    )}
                    {action}
                </div>
            )}
        </div>
    );
}
