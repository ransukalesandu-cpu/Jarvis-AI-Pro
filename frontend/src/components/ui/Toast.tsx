import { create } from 'zustand';
import { Toast as R } from 'radix-ui';
import { X } from 'lucide-react';
import type { Tone } from './types';
import { DURATIONS } from '../../styles/tokens';

export interface ToastMsg {
    id: number;
    title: string;
    description?: string;
    tone?: Tone;
    /** Optional action, e.g. Undo or Retry. */
    action?: { label: string; onClick: () => void };
}

interface ToastStore {
    items: ToastMsg[];
    push: (t: Omit<ToastMsg, 'id'>) => number;
    dismiss: (id: number) => void;
}

let next = 1;
export const useToasts = create<ToastStore>((set) => ({
    items: [],
    push: (t) => {
        const id = next++;
        set((s) => ({ items: [...s.items.slice(-3), { ...t, id }] }));
        return id;
    },
    dismiss: (id) => set((s) => ({ items: s.items.filter((t) => t.id !== id) })),
}));

/** Imperative helper: toast({ title, tone }). */
export const toast = (t: Omit<ToastMsg, 'id'>) => useToasts.getState().push(t);

/** Mount once. Errors stay until dismissed; others auto-hide. F8 focuses the region (Radix hotkey). */
export function Toaster() {
    const { items, dismiss } = useToasts();
    return (
        <R.Provider swipeDirection="right" duration={DURATIONS['dur-toast']}>
            {items.map((t) => (
                <R.Root
                    key={t.id}
                    className="ui-pop ui-toast"
                    data-tone={t.tone ?? 'neutral'}
                    duration={t.tone === 'danger' ? Infinity : undefined}
                    type={t.tone === 'danger' ? 'foreground' : 'background'}
                    onOpenChange={(open) => !open && dismiss(t.id)}
                >
                    <R.Title className="ui-toast-title">{t.title}</R.Title>
                    {t.description && <R.Description className="ui-hint">{t.description}</R.Description>}
                    {t.action && (
                        <R.Action asChild altText={t.action.label}>
                            <button type="button" className="ui-btn" data-variant="outline" data-size="sm" data-tone="neutral" onClick={t.action.onClick}>
                                {t.action.label}
                            </button>
                        </R.Action>
                    )}
                    <R.Close className="ui-icon-btn" aria-label="Dismiss">
                        <X size={14} aria-hidden />
                    </R.Close>
                </R.Root>
            ))}
            <R.Viewport className="ui-toast-viewport" />
        </R.Provider>
    );
}
