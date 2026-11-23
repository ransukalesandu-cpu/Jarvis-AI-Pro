import { forwardRef, type ButtonHTMLAttributes, type ReactNode } from 'react';
import { Slot } from 'radix-ui';
import { LoaderCircle } from 'lucide-react';
import { cx, styleAttrs, type StyleProps } from './types';

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement>, StyleProps {
    /** Shows a spinner, sets aria-busy and blocks clicks; the label stays for screen readers. */
    loading?: boolean;
    /** Render the child element (e.g. a link) with button styling. */
    asChild?: boolean;
    icon?: ReactNode;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
    { variant = 'solid', size, tone = 'primary', loading = false, asChild = false, icon, className, children, disabled, type, ...rest },
    ref,
) {
    const Comp = asChild ? Slot.Root : 'button';
    return (
        <Comp
            ref={ref}
            type={asChild ? undefined : (type ?? 'button')}
            className={cx('ui-btn', className)}
            {...styleAttrs({ variant, size, tone })}
            disabled={disabled || loading}
            aria-busy={loading || undefined}
            {...rest}
        >
            {loading ? <LoaderCircle className="ui-spin" aria-hidden size={14} /> : icon}
            {asChild ? children : children != null && <span className="ui-btn-label">{children}</span>}
        </Comp>
    );
});
