import type { ReactNode } from 'react';
import { Dialog as D } from 'radix-ui';
import { X } from 'lucide-react';
import { cx } from './types';

export interface DialogProps {
    open?: boolean;
    defaultOpen?: boolean;
    onOpenChange?: (open: boolean) => void;
    /** Element that opens the dialog (rendered with asChild). */
    trigger?: ReactNode;
    title: string;
    description?: string;
    children?: ReactNode;
    /** Buttons row; put the primary action last. */
    footer?: ReactNode;
    /** 'sheet' slides from an edge instead of centring. */
    kind?: 'dialog' | 'sheet';
    side?: 'right' | 'left' | 'bottom';
}

/** Modal dialog / sheet: focus trapped, Escape closes, focus returns to the trigger (Radix). */
export function Dialog({ open, defaultOpen, onOpenChange, trigger, title, description, children, footer, kind = 'dialog', side = 'right' }: DialogProps) {
    return (
        <D.Root open={open} defaultOpen={defaultOpen} onOpenChange={onOpenChange}>
            {trigger && <D.Trigger asChild>{trigger}</D.Trigger>}
            <D.Portal>
                <D.Overlay className="ui-overlay" />
                <D.Content className={cx('ui-pop', kind === 'sheet' ? 'ui-sheet' : 'ui-dialog')} data-side={kind === 'sheet' ? side : undefined}>
                    <header className="ui-dialog-head">
                        <D.Title className="ui-dialog-title">{title}</D.Title>
                        <D.Close className="ui-icon-btn" aria-label="Close">
                            <X size={16} aria-hidden />
                        </D.Close>
                    </header>
                    {description ? (
                        <D.Description className="ui-hint">{description}</D.Description>
                    ) : (
                        <D.Description className="ui-sr-only">{title}</D.Description>
                    )}
                    <div className="ui-dialog-body">{children}</div>
                    {footer && <footer className="ui-dialog-foot">{footer}</footer>}
                </D.Content>
            </D.Portal>
        </D.Root>
    );
}

/** Side sheet: the same dialog anchored to an edge. */
export const Sheet = (props: Omit<DialogProps, 'kind'>) => <Dialog {...props} kind="sheet" />;
