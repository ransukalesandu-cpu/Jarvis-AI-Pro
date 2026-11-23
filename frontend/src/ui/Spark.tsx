import { SparkChart } from '../components/ui';

const W = 260,
    H = 44;

/** Sparkline of real samples (Recharts). Never draws a line without data. Screen readers get the numbers. */
export function Spark({ label, data, unit, max, tone = 'cyan' }: { label: string; data: number[]; unit: string; max?: number; tone?: 'cyan' | 'amber' }) {
    const last = data.length ? data[data.length - 1] : null;
    const summary =
        last === null
            ? `${label}: no samples yet`
            : `${label}: now ${Math.round(last)}${unit}, min ${Math.round(Math.min(...data))}, max ${Math.round(Math.max(...data))} over ${data.length} s`;
    return (
        <figure className="spark" data-tone={tone}>
            <figcaption>
                <span>{label}</span>
                <span>{last === null ? '--' : `${Math.round(last)}${unit}`}</span>
            </figcaption>
            {max !== undefined && (
                <div className="spark-meter" aria-hidden>
                    <i style={{ width: `${last === null ? 0 : Math.min(100, (Math.max(0, last) / max) * 100)}%` }} />
                </div>
            )}
            <p className="ui-sr-only">{summary}</p>
            {data.length < 2 ? (
                <p className="spark-empty" aria-hidden>
                    collecting…
                </p>
            ) : (
                <SparkChart data={data} max={max} width={W} height={H} tone={tone === 'amber' ? 'amber' : 'secondary'} />
            )}
        </figure>
    );
}
