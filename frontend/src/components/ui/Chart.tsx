import { Area, AreaChart, YAxis } from 'recharts';

export interface SparkChartProps {
    data: number[];
    max?: number;
    width: number;
    height: number;
    /** Token name used for the line/area colour. */
    tone?: 'primary' | 'secondary' | 'warm' | 'amber';
}

/** Small area chart (Recharts). Decorative to assistive tech: callers give the numbers as text. */
export function SparkChart({ data, max, width, height, tone = 'secondary' }: SparkChartProps) {
    const rows = data.map((v, i) => ({ i, v }));
    const colour = `var(--${tone})`;
    return (
        <div className="ui-chart" aria-hidden="true">
            {/* accessibilityLayer off: it makes the SVG a focusable "application", which a hidden chart must not be. */}
            <AreaChart width={width} height={height} data={rows} margin={{ top: 2, right: 0, bottom: 2, left: 0 }} accessibilityLayer={false}>
                <YAxis hide domain={[0, max ?? 'auto']} />
                <Area type="monotone" dataKey="v" stroke={colour} fill={colour} fillOpacity={0.18} strokeWidth={1.5} isAnimationActive={false} dot={false} />
            </AreaChart>
        </div>
    );
}
