import { readdirSync, readFileSync } from 'node:fs';
import { join } from 'node:path';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { Button, Checkbox, Input, Select, StateView, Table, Tabs, Textarea } from '.';

const html = (el: React.ReactElement) => renderToStaticMarkup(el);

describe('Button', () => {
    it('defaults to type=button and exposes variant/size/tone', () => {
        const h = html(<Button>Go</Button>);
        expect(h).toContain('type="button"');
        expect(h).toContain('data-variant="solid"');
        expect(h).toContain('data-size="md"');
        expect(h).toContain('data-tone="primary"');
    });
    it('loading is busy and disabled, label kept', () => {
        const h = html(<Button loading>Saving</Button>);
        expect(h).toContain('aria-busy="true"');
        expect(h).toContain('disabled=""');
        expect(h).toContain('Saving');
    });
});

describe('fields', () => {
    it('label is tied to the control; error is announced and marks it invalid', () => {
        const h = html(<Input label="Name" error="Required" />);
        const id = /<input[^>]*\sid="([^"]+)"/.exec(h)![1];
        expect(h).toContain(`for="${id}"`);
        expect(h).toContain('aria-invalid="true"');
        expect(h).toMatch(/aria-describedby="[^"]*-err"/);
        expect(h).toContain('role="alert"');
    });
    it('hint is described and hidden when there is an error', () => {
        expect(html(<Textarea label="Notes" hint="Optional" />)).toMatch(/aria-describedby="[^"]*-hint"/);
        expect(html(<Textarea label="Notes" hint="Optional" error="Too long" />)).not.toContain('Optional');
    });
    it('select with no options is disabled and says why', () => {
        const h = html(<Select label="Brain" options={[]} emptyText="None configured" />);
        expect(h).toContain('None configured');
        expect(h).toContain('disabled=""');
    });
    it('checkbox carries its error', () => {
        expect(html(<Checkbox label="Agree" error="Required" />)).toContain('aria-invalid="true"');
    });
});

describe('Table states', () => {
    const base = { caption: 'Jobs', columns: [{ key: 'a', header: 'A', cell: (r: { a: string }) => r.a }], rowKey: (r: { a: string }) => r.a };
    it('rows, empty, loading, error', () => {
        expect(html(<Table {...base} rows={[{ a: 'x' }]} />)).toContain('<td>x</td>');
        expect(html(<Table {...base} rows={[]} emptyText="Nothing" />)).toContain('Nothing');
        expect(html(<Table {...base} rows={[]} loading />)).toContain('aria-busy="true"');
        const err = html(<Table {...base} rows={[]} error="Broken" onRetry={() => {}} />);
        expect(err).toContain('role="alert"');
        expect(err).toContain('Try again');
    });
});

describe('StateView', () => {
    it('loading is a busy status with skeleton lines; error is an alert with retry', () => {
        const l = html(<StateView kind="loading" title="Jobs" />);
        expect(l).toContain('aria-busy="true"');
        expect(l.match(/ui-skeleton/g)?.length).toBe(3);
        const e = html(<StateView kind="error" title="Broken" onRetry={() => {}} />);
        expect(e).toContain('role="alert"');
        expect(e).toContain('Try again');
        expect(html(<StateView kind="offline" title="Offline" />)).toContain('data-kind="offline"');
    });
});

describe('Tabs', () => {
    it('renders a labelled tablist', () => {
        const h = html(<Tabs label="Sections" items={[{ value: 'a', label: 'A', content: 'one' }]} />);
        expect(h).toContain('role="tablist"');
        expect(h).toContain('aria-label="Sections"');
    });
});

describe('every primitive has a story covering its states', () => {
    const dir = __dirname;
    const required: Record<string, string[]> = {
        Button: ['Default', 'Variants', 'Sizes', 'Tones', 'Focus', 'Disabled', 'Loading'],
        Input: ['Default', 'Focus', 'Invalid', 'Disabled', 'Loading'],
        Select: ['Default', 'Invalid', 'Disabled', 'Empty'],
        Checkbox: ['Default', 'Checked', 'Disabled', 'Invalid'],
        Dialog: ['Default', 'Error', 'Loading', 'SheetRight'],
        Popover: ['PopoverDefault', 'TooltipDefault'],
        Tabs: ['Default', 'Disabled'],
        Table: ['Default', 'Loading', 'Empty', 'Error'],
        Toast: ['Default'],
        StateView: ['Loading', 'Empty', 'Error', 'Offline', 'Success'],
    };
    const stories = readdirSync(dir).filter((f) => f.endsWith('.stories.tsx'));
    it.each(Object.entries(required))('%s', (name, exports) => {
        const file = `${name}.stories.tsx`;
        expect(stories).toContain(file);
        const src = readFileSync(join(dir, file), 'utf8');
        for (const e of exports) expect(src).toMatch(new RegExp(`export const ${e}\\b`));
    });
});
