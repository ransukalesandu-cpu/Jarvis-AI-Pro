import type { ReactNode } from 'react';
import { Popover as P, Tooltip as T } from 'radix-ui';

export interface PopoverProps {
    trigger: ReactNode;
    children: ReactNode;
    label: string;
    side?: 'top' | 'right' | 'bottom' | 'left';
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
}

/** Non-modal floating panel; focus moves in and returns on close. */
export function Popover({ trigger, children, label, side = 'bottom', open, onOpenChange }: PopoverProps) {
    return (
        <P.Root open={open} onOpenChange={onOpenChange}>
            <P.Trigger asChild>{trigger}</P.Trigger>
            <P.Portal>
                <P.Content className="ui-pop ui-popover" side={side} sideOffset={6} aria-label={label}>
                    {children}
                    <P.Arrow className="ui-arrow" />
                </P.Content>
            </P.Portal>
        </P.Root>
    );
}

export interface TooltipProps {
    content: string;
    children: ReactNode;
    side?: 'top' | 'right' | 'bottom' | 'left';
}

/** Hover/focus hint. Needs <TooltipProvider> once near the root. Never the only way to get information. */
export function Tooltip({ content, children, side = 'top' }: TooltipProps) {
    return (
        <T.Root>
            <T.Trigger asChild>{children}</T.Trigger>
            <T.Portal>
                <T.Content className="ui-pop ui-tooltip" side={side} sideOffset={6}>
                    {content}
                    <T.Arrow className="ui-arrow" />
                </T.Content>
            </T.Portal>
        </T.Root>
    );
}

export const TooltipProvider = T.Provider;
