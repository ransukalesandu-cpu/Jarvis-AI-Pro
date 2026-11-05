import { useState } from 'react';
import { X } from 'lucide-react';
import { useUi } from '../store';

interface Line { id: number; tag: string; text: string }
export interface Exchange { id: number; you: string | null; reply: string }

const MAX_REPLY_LINES = 6;

/** The latest exchange from the (already redacted and gated) log mirror: the last thing you said and JARVIS's answer to it.
 *  Consecutive JARVIS lines after your last line are joined. Returns null until JARVIS has said something. */
export function latestExchange(log: readonly Line[]): Exchange | null {
  let end = log.length - 1;
  while (end >= 0 && log[end].tag !== 'ai') end--;
  if (end < 0) return null;
  let start = end;
  while (start > 0 && log[start - 1].tag === 'ai' && end - start + 1 < MAX_REPLY_LINES) start--;
  const youLine = log.slice(0, start).reverse().find((l) => l.tag === 'you');
  return { id: log[end].id, you: youLine?.text ?? null, reply: log.slice(start, end + 1).map((l) => l.text).join('\n') };
}

export function ReplyPanelView({ ex, onClose }: { ex: Exchange | null; onClose: () => void }) {
  if (!ex) return null;
  return (
    <aside className="reply glass" aria-label="JARVIS reply" role="region">
      <button className="reply-close" onClick={onClose} aria-label="Dismiss reply"><X size={13} /></button>
      {ex.you && <p className="reply-you">{ex.you}</p>}
      <p className="reply-text" role="status" aria-live="polite">{ex.reply}</p>
    </aside>
  );
}

/** Shows JARVIS's latest answer near the command bar. Read-only; dismissing hides only until the next reply. */
export function ReplyPanel() {
  const log = useUi((s) => s.log);
  const ex = latestExchange(log);
  const [closed, setClosed] = useState<number | null>(null);
  return <ReplyPanelView ex={ex && ex.id !== closed ? ex : null} onClose={() => ex && setClosed(ex.id)} />;
}
