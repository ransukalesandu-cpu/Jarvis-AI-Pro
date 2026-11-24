import { ExternalLink } from 'lucide-react';
import { sendRequest } from '../bridge/bridge';
import type { CommandReason, NewsItem } from '../bridge/contract';
import { useUi } from '../store';
import { ResultNote } from './CommandBar';
import { Button, StateView } from '../components/ui';
import { useT } from '../i18n';

export interface NewsProps {
    heading: string | null;
    items: NewsItem[];
    linked: boolean;
    result: CommandReason | null;
    onOpen: (i: number) => void;
}

/** Headlines JARVIS is showing in the classic HUD, mirrored read-only. The page never sees a URL: "Open" sends the index
 *  and Python opens the link in the system browser (refused while locked / PIN / silent / guest). */
export function NewsView({ heading, items, linked, result, onOpen }: NewsProps) {
    const T = useT();
    return (
        <>
            <h1 className="ui-sr-only">{T('win.news')}</h1>
            {heading && <p>{heading}</p>}
            {items.length === 0 ? (
                <StateView kind="empty" title={T('news.emptyTitle')} message={T('news.empty')} />
            ) : (
                <ul className="news-list">
                    {items.map((n, i) => (
                        <li key={i} className="news-item">
                            <span className="news-title">{n.title}</span>
                            {n.source && <span className="news-source">{n.source}</span>}
                            {n.link && (
                                <Button
                                    variant="outline"
                                    tone="neutral"
                                    size="sm"
                                    disabled={!linked}
                                    onClick={() => onOpen(i)}
                                    aria-label={`Open article in your browser: ${n.title}`}
                                    icon={<ExternalLink size={12} aria-hidden />}
                                >
                                    {T('news.open')}
                                </Button>
                            )}
                        </li>
                    ))}
                </ul>
            )}
            <ResultNote result={result} />
        </>
    );
}

export function NewsContent() {
    const news = useUi((s) => s.news);
    const linked = useUi((s) => s.link) === 'connected';
    const result = useUi((s) => s.control);
    return (
        <NewsView
            heading={news?.heading ?? null}
            items={news?.items ?? []}
            linked={linked}
            result={result}
            onOpen={(index) => sendRequest({ kind: 'news.open', index })}
        />
    );
}
