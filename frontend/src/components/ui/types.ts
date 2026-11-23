/** Props shared by every primitive, mirrored on the Qt side (jarvis/ui/components): variant, size, tone. */
export type Variant = 'solid' | 'outline' | 'ghost';
export type Size = 'sm' | 'md' | 'lg';
export type Tone = 'neutral' | 'primary' | 'ok' | 'warn' | 'danger';

export interface StyleProps {
    variant?: Variant;
    size?: Size;
    tone?: Tone;
}

/** data-* attributes the CSS keys on (no class soup; see src/styles/components.css). */
export const styleAttrs = ({ variant = 'outline', size = 'md', tone = 'neutral' }: StyleProps) => ({
    'data-variant': variant,
    'data-size': size,
    'data-tone': tone,
});

export const cx = (...parts: (string | false | null | undefined)[]) => parts.filter(Boolean).join(' ');
