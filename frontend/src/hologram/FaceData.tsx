import { useEffect, useMemo } from 'react';
import { AdditiveBlending, CanvasTexture, LinearFilter, SRGBColorSpace } from 'three';
import { useUi } from '../store';
import { reshape } from './shape';

const CHIP_TOP_Y = reshape(0, 0.49, 0.45)[1],
    CHIP_LOW_Y = reshape(0, 0.315, 0.5)[1];

/** What one forehead chip shows. `frac` is 0..1 for the meter, null when there is no reading yet. */
export interface ChipData {
    label: string;
    value: string;
    frac: number | null;
    foot?: string;
}

/** The chip readouts from live telemetry. Never invents a number: no sample -> "--". */
export function chipData(metrics: { cpu: number; ram: number } | null, assistant: string): [ChipData, ChipData] {
    const pct = (v: number | undefined) => (v === undefined || !Number.isFinite(v) ? null : Math.max(0, Math.min(100, v)));
    const cpu = pct(metrics?.cpu),
        ram = pct(metrics?.ram);
    return [
        {
            label: 'CPU',
            value: cpu === null ? '--' : `${Math.round(cpu)}%`,
            frac: cpu === null ? null : cpu / 100,
            foot: `JARVIS · ${assistant.toUpperCase()}`,
        },
        { label: 'RAM', value: ram === null ? '--' : `${Math.round(ram)}%`, frac: ram === null ? null : ram / 100 },
    ];
}

const BLUE = '#3cc4ff';

/** Draws one chip: a dark circuit module with a glowing blue frame, a label, a big value and a meter. */
export function drawChip(ctx: CanvasRenderingContext2D, w: number, h: number, d: ChipData): void {
    ctx.clearRect(0, 0, w, h);
    const r = h * 0.12,
        pad = h * 0.08;
    const rr = (x0: number, y0: number, ww: number, hh: number, rad: number) => {
        ctx.beginPath();
        ctx.moveTo(x0 + rad, y0);
        ctx.lineTo(x0 + ww - rad, y0);
        ctx.quadraticCurveTo(x0 + ww, y0, x0 + ww, y0 + rad);
        ctx.lineTo(x0 + ww, y0 + hh - rad);
        ctx.quadraticCurveTo(x0 + ww, y0 + hh, x0 + ww - rad, y0 + hh);
        ctx.lineTo(x0 + rad, y0 + hh);
        ctx.quadraticCurveTo(x0, y0 + hh, x0, y0 + hh - rad);
        ctx.lineTo(x0, y0 + rad);
        ctx.quadraticCurveTo(x0, y0, x0 + rad, y0);
        ctx.closePath();
    };
    // body + glowing frame
    ctx.shadowColor = BLUE;
    ctx.shadowBlur = h * 0.12;
    rr(pad, pad, w - pad * 2, h - pad * 2, r);
    ctx.fillStyle = 'rgba(4, 30, 60, 0.75)';
    ctx.fill();
    ctx.lineWidth = h * 0.025;
    ctx.strokeStyle = BLUE;
    ctx.stroke();
    ctx.shadowBlur = 0;
    // pins on both sides, like a chip
    ctx.fillStyle = 'rgba(60, 196, 255, 0.8)';
    for (let i = 0; i < 4; i++) {
        const py = pad + (h - pad * 2) * (0.22 + i * 0.19);
        ctx.fillRect(pad * 0.1, py, pad * 0.8, h * 0.035);
        ctx.fillRect(w - pad * 0.9, py, pad * 0.8, h * 0.035);
    }
    // label + value
    ctx.shadowColor = BLUE;
    ctx.shadowBlur = h * 0.06;
    ctx.fillStyle = '#9fe3ff';
    ctx.font = `600 ${Math.round(h * 0.15)}px "JetBrains Mono", ui-monospace, monospace`;
    ctx.textBaseline = 'top';
    ctx.fillText(d.label, pad * 2.2, pad * 2);
    ctx.fillStyle = '#e8fbff';
    ctx.font = `700 ${Math.round(h * 0.34)}px "JetBrains Mono", ui-monospace, monospace`;
    ctx.textAlign = 'right';
    ctx.fillText(d.value, w - pad * 2.2, pad * 1.6);
    ctx.textAlign = 'left';
    // meter
    const my = h * (d.foot ? 0.6 : 0.66),
        mh = h * 0.1,
        mw = w - pad * 4.4;
    ctx.shadowBlur = 0;
    ctx.fillStyle = 'rgba(60, 196, 255, 0.15)';
    ctx.fillRect(pad * 2.2, my, mw, mh);
    if (d.frac !== null) {
        ctx.shadowColor = BLUE;
        ctx.shadowBlur = h * 0.08;
        ctx.fillStyle = BLUE;
        ctx.fillRect(pad * 2.2, my, mw * d.frac, mh);
    }
    if (d.foot) {
        ctx.shadowBlur = 0;
        ctx.fillStyle = 'rgba(159, 227, 255, 0.8)';
        ctx.font = `500 ${Math.round(h * 0.1)}px "JetBrains Mono", ui-monospace, monospace`;
        ctx.fillText(d.foot, pad * 2.2, h * 0.76);
    }
}

function useChipTexture(w: number, h: number) {
    return useMemo(() => {
        const canvas = document.createElement('canvas');
        canvas.width = w;
        canvas.height = h;
        const tex = new CanvasTexture(canvas);
        tex.colorSpace = SRGBColorSpace;
        tex.minFilter = LinearFilter;
        return { canvas, tex, ctx: canvas.getContext('2d') };
    }, [w, h]);
}

/**
 * Two glowing blue chips set into the forehead, like the circuit modules of the reference face,
 * showing live CPU and RAM (and the assistant state). They are part of the head, so they turn with it.
 */
export function ForeheadChips() {
    const metrics = useUi((s) => s.metrics);
    const assistant = useUi((s) => s.assistant);
    const top = useChipTexture(512, 300);
    const low = useChipTexture(512, 240);
    useEffect(() => {
        const [a, b] = chipData(metrics, assistant);
        if (top.ctx) {
            drawChip(top.ctx, 512, 300, a);
            top.tex.needsUpdate = true;
        }
        if (low.ctx) {
            drawChip(low.ctx, 512, 240, b);
            low.tex.needsUpdate = true;
        }
    }, [metrics, assistant, top, low]);
    useEffect(
        () => () => {
            top.tex.dispose();
            low.tex.dispose();
        },
        [top, low],
    );
    return (
        <group>
            <mesh position={[0, CHIP_TOP_Y, 0.45]} rotation={[-0.42, 0, 0]} renderOrder={7}>
                <planeGeometry args={[0.36, 0.21]} />
                <meshBasicMaterial map={top.tex} transparent blending={AdditiveBlending} depthWrite={false} depthTest={false} />
            </mesh>
            <mesh position={[0, CHIP_LOW_Y, 0.5]} rotation={[-0.22, 0, 0]} renderOrder={7}>
                <planeGeometry args={[0.27, 0.127]} />
                <meshBasicMaterial map={low.tex} transparent blending={AdditiveBlending} depthWrite={false} depthTest={false} />
            </mesh>
        </group>
    );
}
