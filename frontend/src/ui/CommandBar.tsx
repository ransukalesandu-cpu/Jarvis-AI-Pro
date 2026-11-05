import { useEffect, useRef, useState } from 'react';
import { SendHorizonal } from 'lucide-react';
import { COMMAND_MAX, type CommandReason, type CommandState } from '../bridge/contract';
import { sendRequest } from '../bridge/bridge';
import { useUi } from '../store';

export const BLOCKED: Record<Exclude<CommandState, 'ok'>, string> = {
  locked: 'JARVIS is locked. Unlock it with the native prompt.',
  auth_required: 'Authentication needed. Use the native prompt, never this box.',
  silent: 'JARVIS is in silent mode.',
  guest: 'Guest mode. Typed commands are disabled here.',
  unavailable: 'Typing to JARVIS is not available in this window yet.',
};
export const RESULT: Record<CommandReason, string> = {
  sent: 'Sent', empty: 'Nothing to send', too_long: `Too long (max ${COMMAND_MAX})`, rate_limited: 'Too fast, try again in a moment',
  credential: 'That looks like a credential. It was not sent. Use the native prompt.',
  locked: BLOCKED.locked, auth_required: BLOCKED.auth_required, silent: BLOCKED.silent, guest: BLOCKED.guest, unavailable: BLOCKED.unavailable,
};

export interface ViewProps {
  state: CommandState; last: CommandReason | null; linked: boolean; text: string;
  onText: (t: string) => void; onSubmit: (e: React.FormEvent) => void; inputRef?: React.Ref<HTMLInputElement>;
}

/** Pure view: everything it shows comes from props, so it is easy to test. */
export function CommandBarView({ state, last, linked, text, onText, onSubmit, inputRef }: ViewProps) {
  const ok = state === 'ok' && linked;
  const note = ok ? (last ? RESULT[last] : '') : state === 'ok' ? 'Connecting…' : BLOCKED[state];
  return (
    <form className="cmdbar glass" onSubmit={onSubmit} role="search" aria-label="Ask JARVIS">
      <input ref={inputRef} value={text} onChange={(e) => onText(e.target.value)} maxLength={COMMAND_MAX} disabled={!ok}
        placeholder={ok ? 'Ask JARVIS…  (Ctrl+L)' : 'Typing is unavailable'} aria-label="Command for JARVIS"
        autoComplete="off" spellCheck={false} type="text" name="jarvis-command" />
      <button type="submit" disabled={!ok || !text.trim()} aria-label="Send"><SendHorizonal size={16} /></button>
      <span className="cmdbar-note" role="status" aria-live="polite">{note}</span>
    </form>
  );
}

/** Ask JARVIS. The only write path from the page; Python decides whether it is allowed. Never use for secrets. */
export function CommandBar() {
  const { state, last } = useUi((s) => s.command);
  const linked = useUi((s) => s.link) === 'connected';
  const [text, setText] = useState('');
  const ref = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const on = () => ref.current?.focus();
    addEventListener('jarvis:focus-command', on);
    return () => removeEventListener('jarvis:focus-command', on);
  }, []);

  const submit = (e: React.FormEvent) => {
    e.preventDefault();
    const t = text.trim();
    if (state !== 'ok' || !linked || !t) return;
    sendRequest({ kind: 'command.submit', text: t });
    setText('');                         // the text is never kept in the page after it is sent
  };
  return <CommandBarView state={state} last={last} linked={linked} text={text} onText={setText} onSubmit={submit} inputRef={ref} />;
}
