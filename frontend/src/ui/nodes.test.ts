import { renderToStaticMarkup } from 'react-dom/server';
import { createElement } from 'react';
import { describe, expect, it } from 'vitest';
import { parseHostEvent, type NodeRow } from '../bridge/contract';
import { NodesView } from './Nodes';

const j = (o: unknown) => JSON.stringify(o);
const node = (extra: Partial<NodeRow> = {}): NodeRow => ({ name: 'forge', status: 'online', cpu: 12, ramFreeMb: 6100, running: 1, queued: 0, lastOkAt: 1_000_000, ...extra });

describe('nodes.updated', () => {
  it('accepts valid rows, including unknown load as null', () => {
    expect(parseHostEvent(j({ type: 'nodes.updated', nodes: [node()] }))).toEqual({ type: 'nodes.updated', nodes: [node()] });
    const offline = node({ status: 'offline', cpu: null, ramFreeMb: null, running: null, queued: null, lastOkAt: null });
    expect(parseHostEvent(j({ type: 'nodes.updated', nodes: [offline] }))?.type).toBe('nodes.updated');
  });
  it('rejects extra fields (no address, token or error text may reach the page), bad states and ranges', () => {
    expect(parseHostEvent(j({ type: 'nodes.updated', nodes: [{ ...node(), url: 'https://forge:8770/mcp' }] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'nodes.updated', nodes: [{ ...node(), status: 'hacked' }] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'nodes.updated', nodes: [node({ cpu: 140 })] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'nodes.updated', nodes: [node({ name: '' })] }))).toBeNull();
    expect(parseHostEvent(j({ type: 'nodes.updated', nodes: Array(9).fill(node()) }))).toBeNull();
  });
});

describe('NodesView', () => {
  const html = (nodes: NodeRow[] | null) => renderToStaticMarkup(createElement(NodesView, { nodes, now: 1_030_000 }));
  it('shows status and real load, and says plainly when a node is offline', () => {
    expect(html([node()])).toContain('forge · Online');
    expect(html([node()])).toContain('CPU 12% · 6.1 GB free');
    expect(html([node()])).toContain('last answer 30s ago');
    const off = html([node({ status: 'offline', cpu: null, ramFreeMb: null, running: null, queued: null, lastOkAt: null })]);
    expect(off).toContain('Offline');
    expect(off).toContain('no answer yet');
    expect(off).not.toContain('CPU');
  });
  it('says when nothing is configured', () => {
    expect(html(null)).toContain('No worker node is configured');
  });
});
