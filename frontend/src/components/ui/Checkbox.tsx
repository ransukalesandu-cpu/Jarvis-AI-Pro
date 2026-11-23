import { useId } from 'react';
import { Checkbox as C } from 'radix-ui';
import { Check, Minus } from 'lucide-react';

export interface CheckboxProps {
    label: string;
    checked?: boolean | 'indeterminate';
    defaultChecked?: boolean;
    onCheckedChange?: (v: boolean) => void;
    disabled?: boolean;
    hint?: string;
    error?: string;
}

export function Checkbox({ label, checked, defaultChecked, onCheckedChange, disabled, hint, error }: CheckboxProps) {
    const id = useId();
    const describedBy = error ? `${id}-err` : hint ? `${id}-hint` : undefined;
    return (
        <div className="ui-check-row" data-invalid={error ? 'true' : undefined}>
            <C.Root
                id={id}
                className="ui-check"
                checked={checked}
                defaultChecked={defaultChecked}
                onCheckedChange={(v) => onCheckedChange?.(v === true)}
                disabled={disabled}
                aria-invalid={error ? true : undefined}
                aria-describedby={describedBy}
            >
                <C.Indicator className="ui-check-mark">
                    {checked === 'indeterminate' ? <Minus size={12} aria-hidden /> : <Check size={12} aria-hidden />}
                </C.Indicator>
            </C.Root>
            <label htmlFor={id} className="ui-label">
                {label}
            </label>
            {hint && !error && (
                <p className="ui-hint" id={`${id}-hint`}>
                    {hint}
                </p>
            )}
            {error && (
                <p className="ui-error" id={`${id}-err`} role="alert">
                    {error}
                </p>
            )}
        </div>
    );
}
