import { Select as S } from 'radix-ui';
import { Check, ChevronDown } from 'lucide-react';
import { styleAttrs, type Size } from './types';
import { Field } from './Field';

export interface SelectOption {
    value: string;
    label: string;
    disabled?: boolean;
}

export interface SelectProps {
    label: string;
    options: SelectOption[];
    value?: string;
    defaultValue?: string;
    onValueChange?: (v: string) => void;
    placeholder?: string;
    hint?: string;
    error?: string;
    disabled?: boolean;
    size?: Size;
    /** Text shown when there are no options. */
    emptyText?: string;
}

export function Select({
    label,
    options,
    value,
    defaultValue,
    onValueChange,
    placeholder = 'Choose…',
    hint,
    error,
    disabled,
    size,
    emptyText = 'Nothing to choose from',
}: SelectProps) {
    const empty = options.length === 0;
    return (
        <Field label={label} hint={hint} error={error}>
            {({ id, describedBy, invalid }) => (
                <S.Root value={value} defaultValue={defaultValue} onValueChange={onValueChange} disabled={disabled || empty}>
                    <S.Trigger
                        id={id}
                        className="ui-input ui-select"
                        {...styleAttrs({ size })}
                        aria-invalid={invalid || undefined}
                        aria-describedby={describedBy}
                    >
                        <S.Value placeholder={empty ? emptyText : placeholder} />
                        <S.Icon className="ui-select-icon">
                            <ChevronDown size={14} aria-hidden />
                        </S.Icon>
                    </S.Trigger>
                    <S.Portal>
                        <S.Content className="ui-pop ui-select-content" position="popper" sideOffset={4}>
                            <S.Viewport>
                                {options.map((o) => (
                                    <S.Item key={o.value} value={o.value} disabled={o.disabled} className="ui-select-item">
                                        <S.ItemText>{o.label}</S.ItemText>
                                        <S.ItemIndicator className="ui-select-check">
                                            <Check size={14} aria-hidden />
                                        </S.ItemIndicator>
                                    </S.Item>
                                ))}
                            </S.Viewport>
                        </S.Content>
                    </S.Portal>
                </S.Root>
            )}
        </Field>
    );
}
