import { encodeRequest, parseHostEvent, type UiRequest } from './contract';
import { useUi } from '../store';
import { useWindows } from '../workspace/windows';
import { usePending } from '../ux/pending';
import { onHostEvent, onRequest, resetActions, setResync } from '../ux/actions';

interface QtChannelObject { event: { connect: (fn: (s: string) => void) => void; disconnect?: (fn: (s: string) => void) => void }; request: (s: string) => void }
declare global { interface Window { qt?: { webChannelTransport?: unknown }; QWebChannel?: new (t: unknown, cb: (c: { objects: Record<string, QtChannelObject> }) => void) => unknown } }

let started = false;
let channelObj: QtChannelObject | null = null;
let onEvent: ((s: string) => void) | null = null;

function loadChannelScript(): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.QWebChannel) return resolve();
    const s = document.createElement('script');
    s.src = 'qrc:///qtwebchannel/qwebchannel.js';
    s.onload = () => resolve();
    s.onerror = () => reject(new Error('qwebchannel.js unavailable'));
    document.head.appendChild(s);
  });
}

/** Connect to the Python host. Outside Qt (plain browser, tests) the link stays 'detached' and no data is invented. */
export async function startBridge(): Promise<void> {
  if (started) return; // never register listeners twice
  started = true;
  const store = useUi.getState();
  if (!window.qt?.webChannelTransport) { store.setLink('detached'); return; }
  usePending.getState().begin('startup', 'startup', 'Connecting to JARVIS');
  setResync(() => sendRequest({ kind: 'workspace.list' }));
  try {
    await loadChannelScript();
    await new Promise<void>((resolve) => {
      new window.QWebChannel!(window.qt!.webChannelTransport, (ch) => {
        channelObj = ch.objects.jarvis ?? null;
        resolve();
      });
    });
    if (!channelObj) { store.setLink('detached'); usePending.getState().end('startup', false); return; }
    onEvent = (raw: string) => { const ev = parseHostEvent(raw); if (!ev) return;
      useUi.getState().apply(ev);
      onHostEvent(ev);
      if (ev.type === 'workspace.loaded' && ev.layout) useWindows.getState().apply(ev.layout);
      if (ev.type === 'host.hello') { sendRequest({ kind: 'workspace.list' }); sendRequest({ kind: 'workspace.load', name: '_last' }); } };
    channelObj.event.connect(onEvent);
    sendRequest({ kind: 'ready' });
  } catch {
    store.setLink('detached');
    usePending.getState().end('startup', false);
  }
}

export function sendRequest(r: UiRequest): void {
  if (channelObj) onRequest(r);
  try { channelObj?.request(encodeRequest(r)); } catch { /* host gone; the heartbeat in Python will reload the page */ }
}

export function stopBridge(): void {
  if (channelObj && onEvent) channelObj.event.disconnect?.(onEvent);
  channelObj = null; onEvent = null; started = false; resetActions();
}
