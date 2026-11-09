import type { NodeRow } from '../bridge/contract';
import { useUi } from '../store';
import { useNow } from '../ux/usePhase';

const LABEL = { unknown: 'Checking…', online: 'Online', degraded: 'Low on resources', offline: 'Offline', incompatible: 'Needs an update', unconfigured: 'Not set up on this PC' } as const;

function ago(ms: number): string {
  const s = Math.max(0, Math.round(ms / 1000));
  return s < 120 ? `${s}s ago` : `${Math.round(s / 60)} min ago`;
}

export interface NodesProps { nodes: NodeRow[] | null; now: number }

/** Worker nodes reported by Python: status and coarse load only. Read-only: nothing here sends work anywhere. */
export function NodesView({ nodes, now }: NodesProps) {
  return (
    <>
      <h1>Worker Nodes</h1>
      <p>The dedicated device that runs background and engineering jobs for this laptop.</p>
      {nodes === null ? <p>No worker node is configured.</p> : nodes.length === 0 ? <p>No worker node is configured.</p> : (
        <ul className="news-list">
          {nodes.map((n) => (
            <li key={n.name} className="news-item">
              <span className="news-title">{n.name} · {LABEL[n.status]}</span>
              <span className="news-source">
                {n.cpu !== null && n.ramFreeMb !== null ? `CPU ${Math.round(n.cpu)}% · ${(n.ramFreeMb / 1000).toFixed(1)} GB free · ` : ''}
                {n.running !== null && n.queued !== null ? `${n.running} running, ${n.queued} queued · ` : ''}
                {n.lastOkAt !== null ? `last answer ${ago(now - n.lastOkAt)}` : 'no answer yet'}
              </span>
            </li>
          ))}
        </ul>
      )}
    </>
  );
}

export function NodesContent() {
  const nodes = useUi((s) => s.nodes);
  const now = useNow(!!nodes?.length, 5000);
  return <NodesView nodes={nodes} now={now} />;
}
