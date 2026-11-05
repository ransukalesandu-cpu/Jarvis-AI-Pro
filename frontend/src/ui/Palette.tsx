import { Command } from 'cmdk';
import { useState } from 'react';
import { sendRequest } from '../bridge/bridge';
import { useUi } from '../store';
import { PAGES } from './Chrome';
import { TITLES, type WinKind, validateLayout } from '../workspace/layout';
import { useWindows } from '../workspace/windows';

const clean = (s: string) => s.trim().toLowerCase();
const NAME = /^[a-z0-9][a-z0-9 _-]{0,31}$/;

/** Ctrl+K. Only actions that are implemented and need no extra authorisation are offered. */
export function Palette() {
  const { paletteOpen, setPalette, go, toggleSettings, workspaceNames, reducedMotion, setReducedMotion, page, link } = useUi();
  const [q, setQ] = useState('');
  const run = (fn: () => void) => () => { fn(); setPalette(false); setQ(''); };
  const w = useWindows.getState;
  const wsName = clean(q);
  const connected = link === 'connected';
  return (
    <Command.Dialog open={paletteOpen} onOpenChange={(o) => { setPalette(o); if (!o) setQ(''); }} label="Command palette" className="palette glass" overlayClassName="palette-overlay" shouldFilter>
      <Command.Input value={q} onValueChange={setQ} placeholder="Type a command…" aria-label="Command" />
      <Command.List>
        <Command.Empty>No matching command.</Command.Empty>
        <Command.Group heading="Navigate">
          {PAGES.filter((p) => p.ready).map((p) => <Command.Item key={p.id} value={`go ${p.label}`} onSelect={run(() => go(p.id))}>{p.icon}<span>{p.label}</span></Command.Item>)}
        </Command.Group>
        <Command.Group heading="Assistant">
          <Command.Item value="ask jarvis type a command" onSelect={run(() => setTimeout(() => dispatchEvent(new Event('jarvis:focus-command')), 0))}>Ask JARVIS…</Command.Item>
        </Command.Group>
        <Command.Group heading="Windows">
          {(Object.keys(TITLES) as WinKind[]).map((k) => <Command.Item key={k} value={`open window ${TITLES[k]}`} onSelect={run(() => { w().open(k); })}>Open {TITLES[k]} window</Command.Item>)}
          <Command.Item value="tile windows arrange" onSelect={run(() => w().tileAll())}>Tile windows</Command.Item>
          <Command.Item value="minimize all windows" onSelect={run(() => w().minimizeAll())}>Minimise all windows</Command.Item>
          <Command.Item value="close all windows show hologram" onSelect={run(() => { w().closeAll(); go('home'); })}>Close all windows (show hologram)</Command.Item>
        </Command.Group>
        <Command.Group heading="Settings">
          <Command.Item value="open settings" onSelect={run(() => toggleSettings(true))}>Open settings</Command.Item>
          <Command.Item value="toggle reduced motion" onSelect={run(() => setReducedMotion(!reducedMotion))}>Toggle reduced motion</Command.Item>
        </Command.Group>
        <Command.Group heading="Workspaces">
          {connected && NAME.test(wsName) && <Command.Item value={`save workspace ${wsName}`} forceMount onSelect={run(() => {
            const layout = validateLayout(w().snapshot(page));
            if (layout) sendRequest({ kind: 'workspace.save', name: wsName, layout });
          })}>Save workspace “{wsName}”</Command.Item>}
          {connected && workspaceNames.map((n) => <Command.Item key={`l-${n}`} value={`load workspace ${n}`} onSelect={run(() => sendRequest({ kind: 'workspace.load', name: n }))}>Load workspace “{n}”</Command.Item>)}
          {connected && workspaceNames.map((n) => <Command.Item key={`d-${n}`} value={`delete workspace ${n}`} onSelect={run(() => sendRequest({ kind: 'workspace.delete', name: n }))}>Delete workspace “{n}”</Command.Item>)}
          {!connected && <Command.Item value="workspaces unavailable" disabled>Workspaces need the backend connection</Command.Item>}
        </Command.Group>
      </Command.List>
    </Command.Dialog>
  );
}
