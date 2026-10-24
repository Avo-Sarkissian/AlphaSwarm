// Hover/pin card for one agent: its signal (THINKING while pending), and who it
// cited and who cited it in the round on screen (docs/DECISIONS.md#adr-hero-graph).
import { signalClass, signalLabel } from '../lib/signals';
import type { AgentView } from '../types';
import type { EgoNetwork } from './edges';

export interface AgentTooltipProps {
  agent: AgentView;
  /** Anchor in canvas px (the node's right edge, vertically centred). */
  x: number;
  y: number;
  canvasWidth: number;
  ego: EgoNetwork;
  edgesRound: number | null;
  pinned: boolean;
  onInterview?: (agentId: string) => void;
}

const CARD_WIDTH = 230;
const MAX_IDS = 3;

function idList(ids: readonly string[]): string {
  if (ids.length === 0) return '—';
  const shown = ids.slice(0, MAX_IDS).join(', ');
  return ids.length > MAX_IDS ? `${shown} +${ids.length - MAX_IDS}` : shown;
}

export function AgentTooltip({ agent, x, y, canvasWidth, ego, edgesRound, pinned, onInterview }: AgentTooltipProps) {
  const flip = x + 12 + CARD_WIDTH > canvasWidth;
  const left = flip ? Math.max(0, x - 24 - CARD_WIDTH) : x + 12;
  const pending = agent.signal === null;
  const cited = ego.incoming.map((e) => e.target_id);
  const citedBy = ego.outgoing.map((e) => e.source_id);
  return (
    <div
      className="tooltip ig-tooltip"
      data-pinned={pinned}
      style={{ left, top: Math.max(0, y - 20), width: CARD_WIDTH }}
    >
      <div className="t-head">
        {agent.id} <span className="t-sub">· {agent.bracketDisplay}</span>
      </div>
      <div className="t-row">
        <span>Signal</span>
        <strong className={signalClass(agent.signal)}>{pending ? 'THINKING' : signalLabel(agent.signal)}</strong>
      </div>
      <div className="t-row">
        <span>Confidence</span>
        <strong>{pending ? '—' : `${Math.round(agent.confidence * 100)}%`}</strong>
      </div>
      {edgesRound === null ? (
        <div className="t-note">Citations appear from round 2.</div>
      ) : (
        <>
          <div className="t-row">
            <span>Cited by (R{edgesRound})</span>
            <strong>{citedBy.length}</strong>
          </div>
          <div className="t-row t-ids">
            <span>Cited by</span>
            <strong>{idList(citedBy)}</strong>
          </div>
          <div className="t-row t-ids">
            <span>Cites</span>
            <strong>{idList(cited)}</strong>
          </div>
        </>
      )}
      {pinned ? (
        <button type="button" className="btn ghost t-action" onClick={() => onInterview?.(agent.id)}>
          Interview {agent.id} →
        </button>
      ) : (
        <div className="t-note">Click to pin · Esc to unpin</div>
      )}
    </div>
  );
}
