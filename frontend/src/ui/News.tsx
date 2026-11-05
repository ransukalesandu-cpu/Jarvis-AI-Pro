import { ExternalLink } from 'lucide-react';
import { sendRequest } from '../bridge/bridge';
import type { CommandReason, NewsItem } from '../bridge/contract';
import { useUi } from '../store';
import { RESULT } from './CommandBar';

export interface NewsProps { heading: string | null; items: NewsItem[]; linked: boolean; result: CommandReason | null; onOpen: (i: number) => void }

/** Headlines JARVIS is showing in the classic HUD, mirrored read-only. The page never sees a URL: "Open" sends the index
 *  and Python opens the link in the system browser (refused while locked / PIN / silent / guest). */
export function NewsView({ heading, items, linked, result, onOpen }: NewsProps) {
  return (
    <>
      <h1>News</h1>
      <p>{heading ? heading : 'Headlines appear here when you ask JARVIS for the news.'}</p>
      {items.length === 0 ? <p>No headlines yet.</p> : (
        <ul className="news-list">
          {items.map((n, i) => (
            <li key={i} className="news-item">
              <span className="news-title">{n.title}</span>
              {n.source && <span className="news-source">{n.source}</span>}
              {n.link && <button className="toggle" disabled={!linked} onClick={() => onOpen(i)} aria-label={`Open article in your browser: ${n.title}`}><ExternalLink size={12} /> Open</button>}
            </li>
          ))}
        </ul>
      )}
      <p className="settings-note" role="status" aria-live="polite">{result && result !== 'done' ? RESULT[result] : ''}</p>
    </>
  );
}

export function NewsContent() {
  const news = useUi((s) => s.news);
  const linked = useUi((s) => s.link) === 'connected';
  const result = useUi((s) => s.control);
  return <NewsView heading={news?.heading ?? null} items={news?.items ?? []} linked={linked} result={result} onOpen={(index) => sendRequest({ kind: 'news.open', index })} />;
}
