import { useId, type ReactNode } from 'react';

export interface FieldProps {
    label: ReactNode;
    hint?: ReactNode;
    /** Error text: marks the control invalid and is announced (aria-describedby + role="alert"). */
    error?: ReactNode;
    children: (ids: { id: string; describedBy: string | undefined; invalid: boolean }) => ReactNode;
}

/** Label + control + hint/error wiring shared by Input, Textarea, Select and Checkbox. */
export function Field({ label, hint, error, children }: FieldProps) {
    const id = useId();
    const hintId = hint ? `${id}-hint` : undefined;
    const errId = error ? `${id}-err` : undefined;
    const describedBy = [hintId, errId].filter(Boolean).join(' ') || undefined;
    return (
        <div className="ui-field" data-invalid={error ? 'true' : undefined}>
            <label className="ui-label" htmlFor={id}>
                {label}
            </label>
            {children({ id, describedBy, invalid: Boolean(error) })}
            {hint && !error && (
                <p className="ui-hint" id={hintId}>
                    {hint}
                </p>
            )}
            {error && (
                <p className="ui-error" id={errId} role="alert">
                    {error}
                </p>
            )}
        </div>
    );
}
