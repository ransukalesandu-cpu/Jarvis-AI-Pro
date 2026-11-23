import type { ReactNode } from 'react';
import { Tabs as R } from 'radix-ui';

export interface TabItem {
    value: string;
    label: string;
    content: ReactNode;
    disabled?: boolean;
}

export interface TabsProps {
    label: string;
    items: TabItem[];
    value?: string;
    defaultValue?: string;
    onValueChange?: (v: string) => void;
}

/** Arrow keys move between tabs, Tab moves into the panel (WAI-ARIA tabs pattern, from Radix). */
export function Tabs({ label, items, value, defaultValue, onValueChange }: TabsProps) {
    return (
        <R.Root className="ui-tabs" value={value} defaultValue={defaultValue ?? items[0]?.value} onValueChange={onValueChange}>
            <R.List className="ui-tab-list" aria-label={label}>
                {items.map((t) => (
                    <R.Trigger key={t.value} value={t.value} disabled={t.disabled} className="ui-tab">
                        {t.label}
                    </R.Trigger>
                ))}
            </R.List>
            {items.map((t) => (
                <R.Content key={t.value} value={t.value} className="ui-tab-panel">
                    {t.content}
                </R.Content>
            ))}
        </R.Root>
    );
}
