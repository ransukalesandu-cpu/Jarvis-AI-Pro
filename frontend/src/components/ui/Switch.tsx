import { Switch as R, ToggleGroup as G } from 'radix-ui';
import { styleAttrs, type Size } from './types';

export interface SwitchProps {
    checked: boolean;
    onCheckedChange: (v: boolean) => void;
    /** Accessible name when no visible <label htmlFor> points at it. */
    label?: string;
    id?: string;
    disabled?: boolean;
    /** Text shown next to the thumb (On/Off); the state is also exposed as role=switch + aria-checked. */
    showState?: boolean;
}

/** On/off setting (role="switch"). Space toggles. */
export function Switch({ checked, onCheckedChange, label, id, disabled, showState = true }: SwitchProps) {
    return (
        <R.Root id={id} className="ui-switch" checked={checked} onCheckedChange={onCheckedChange} disabled={disabled} aria-label={label}>
            <R.Thumb className="ui-switch-thumb" />
            {showState && (
                <span className="ui-switch-text" aria-hidden>
                    {checked ? 'On' : 'Off'}
                </span>
            )}
        </R.Root>
    );
}

export interface SegmentOption {
    value: string;
    label: string;
    disabled?: boolean;
}

export interface SegmentedProps {
    label: string;
    options: SegmentOption[];
    value: string;
    onValueChange: (v: string) => void;
    disabled?: boolean;
    size?: Size;
}

/** One-of-many choice shown as joined buttons (Radix ToggleGroup, single): arrows move, Space picks. */
export function Segmented({ label, options, value, onValueChange, disabled, size = 'sm' }: SegmentedProps) {
    return (
        <G.Root
            type="single"
            className="ui-seg"
            aria-label={label}
            value={value}
            onValueChange={(v) => v && onValueChange(v)}
            disabled={disabled}
            {...styleAttrs({ size })}
        >
            {options.map((o) => (
                <G.Item key={o.value} value={o.value} disabled={o.disabled} className="ui-seg-item">
                    {o.label}
                </G.Item>
            ))}
        </G.Root>
    );
}
