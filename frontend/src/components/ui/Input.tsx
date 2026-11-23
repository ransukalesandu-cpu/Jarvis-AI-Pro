import { forwardRef, type InputHTMLAttributes, type TextareaHTMLAttributes } from 'react';
import { cx, styleAttrs, type Size } from './types';
import { Field } from './Field';

interface Common {
    label: string;
    hint?: string;
    error?: string;
    size?: Size;
    /** Shows a busy state (e.g. while a value is checked). */
    loading?: boolean;
}

export type InputProps = Omit<InputHTMLAttributes<HTMLInputElement>, 'size'> & Common;

export const Input = forwardRef<HTMLInputElement, InputProps>(function Input({ label, hint, error, size, loading, className, ...rest }, ref) {
    return (
        <Field label={label} hint={hint} error={error}>
            {({ id, describedBy, invalid }) => (
                <input
                    ref={ref}
                    id={id}
                    className={cx('ui-input', className)}
                    {...styleAttrs({ size })}
                    aria-invalid={invalid || undefined}
                    aria-describedby={describedBy}
                    aria-busy={loading || undefined}
                    {...rest}
                />
            )}
        </Field>
    );
});

export type TextareaProps = TextareaHTMLAttributes<HTMLTextAreaElement> & Common;

export const Textarea = forwardRef<HTMLTextAreaElement, TextareaProps>(function Textarea({ label, hint, error, size, loading, className, ...rest }, ref) {
    return (
        <Field label={label} hint={hint} error={error}>
            {({ id, describedBy, invalid }) => (
                <textarea
                    ref={ref}
                    id={id}
                    className={cx('ui-input', 'ui-textarea', className)}
                    {...styleAttrs({ size })}
                    aria-invalid={invalid || undefined}
                    aria-describedby={describedBy}
                    aria-busy={loading || undefined}
                    {...rest}
                />
            )}
        </Field>
    );
});
