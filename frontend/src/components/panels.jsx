// Side panels — brackets list, rationale feed, KPI strip, consensus ring.
// WAVE-2-NOTE (Plan 41.1-03): wired to split contexts from Plan 02:
//   KpiStrip       → useTelemetry + useAgents (consensus derivation only)
//   BracketList    → useBrackets
//   RationaleFeed  → useRationales + DOMPurify/marked (T-41.1-01 mitigation)
//   ConsensusRing  → useAgents
// No component here reads the old single-context hook, the Wave-1 global
// data bag, or the deleted mocks/data module.
import DOMPurify from 'dompurify';
import { marked } from 'marked';
import { useTelemetry } from '../context/TelemetryContext';
import { useAgents } from '../context/AgentsContext';
import { useBrackets } from '../context/BracketContext';
import { useRationales } from '../context/RationalesContext';

// ── helpers ────────────────────────────────────────────────────────────
function countSignals(agents) {
  let buy = 0, sell = 0, hold = 0;
  for (const a of agents) {
    if (a.signal === 'buy') buy++;
    else if (a.signal === 'sell') sell++;
    else hold++;
  }
  return { buy, sell, hold };
}

function dominantLabel({ buy, sell, hold }) {
  if (buy >= sell && buy >= hold) return 'BUY';
  if (sell >= hold) return 'SELL';
  return 'HOLD';
}

function formatElapsed(s) {
  const sec = Math.max(0, Math.round(s));
  return `${String(Math.floor(sec / 60)).padStart(2, '0')}:${String(sec % 60).padStart(2, '0')}`;
}

function roundLabelFrom(phase) {
  // Backend phase values: 'idle' | 'initializing' | 'seeding' | 'round_1'
  // | 'round_2' | 'round_3' | 'complete' | 'replay'.
  // Wave 2 maps to R1/R2/R3/FINAL per CONTEXT.md.
  if (phase === 'round_1' || phase === 1) return 'R1';
  if (phase === 'round_2' || phase === 2) return 'R2';
  if (phase === 'round_3' || phase === 3) return 'R3';
  if (phase === 'complete' || phase === 'done') return 'FINAL';
  return '—';
}

// ── BracketList ────────────────────────────────────────────────────────
// Subscribes to useBrackets (BracketContext). Wave 1 prop shape kept
// for backwards-compat — if a parent still passes `summaries`, we prefer
// the context value once it has data.
export function BracketList({ onClick }) {
  const { brackets } = useBrackets();
  // brackets may be [] before first frame — render empty.
  return (
    <div>
      {brackets.map((s) => {
        const bp = s.buy / Math.max(1, s.total);
        const sp = s.sell / Math.max(1, s.total);
        const hp = s.hold / Math.max(1, s.total);
        return (
          <div
            key={s.bracket}
            className="bracket-row"
            onClick={() => onClick && onClick(s)}
          >
            <span className="bracket-chip" style={{ background: 'var(--accent)' }} />
            <span className="bracket-name">{s.display}</span>
            <span className="bracket-count num">{s.total}</span>
            <div className="bracket-bar">
              <span className="b-buy"  style={{ width: `${bp * 100}%` }} />
              <span className="b-sell" style={{ width: `${sp * 100}%` }} />
              <span className="b-hold" style={{ width: `${hp * 100}%` }} />
            </div>
            <span className="bracket-conf num" style={{ marginLeft: 8 }}>
              {Math.round(100 * (s.avgConfidence || 0))}%
            </span>
          </div>
        );
      })}
    </div>
  );
}

// ── RationaleFeed ──────────────────────────────────────────────────────
// Subscribes to useRationales only — isolated from agent ticks. Renders
// markdown safely via DOMPurify.sanitize(marked.parse(...)). The backend
// RationaleEntry shape provides agentId / round / text / citations /
// sources / ts; citations + sources are stubbed [] by Plan 02 adapter
// (KR-41.1-10) so we fall back safely.
export function RationaleFeed({ onAgentClick, onCiteClick }) {
  const { rationales } = useRationales();
  return (
    <div>
      {rationales.map((r, i) => {
        const key = `${r.agentId}-${r.round}-${r.ts}-${i}`;
        const html = DOMPurify.sanitize(marked.parse(r.text || ''));
        const cites = r.citations || [];
        return (
          <div key={key} className="rationale-item">
            <div className="rationale-head">
              <span
                className="rationale-agent"
                onClick={() => onAgentClick && onAgentClick(r.agentId)}
                style={{ cursor: 'pointer' }}
              >
                {r.agentId}
              </span>
              <span className="rationale-round">R{r.round}</span>
            </div>
            <div
              className="rationale-body"
              // T-41.1-01: this is the ONLY markdown→HTML path in panels.jsx.
              dangerouslySetInnerHTML={{ __html: html }}
            />
            {cites.length > 0 && (
              <div className="rationale-cites">
                {cites.map((c, j) => (
                  <span
                    key={j}
                    className="cite"
                    onClick={() => onCiteClick && onCiteClick(c)}
                  >
                    ↳ {c}
                  </span>
                ))}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}

// ── KpiStrip ───────────────────────────────────────────────────────────
// Lightest-subscription component — reads telemetry+phase from
// useTelemetry and derives signal counts via useAgents only for the
// consensus chip. Plan 02 KR-41.1-04 contract: memMb is percent; KR-41.1-05:
// slotsUsed/slotsMax are stubbed 0/8 from the adapter.
export function KpiStrip() {
  const { telemetry: t, phase } = useTelemetry();
  const { agents } = useAgents();
  const counts = countSignals(agents);
  const totalAgents = Math.max(1, agents.length || counts.buy + counts.sell + counts.hold);
  const leader = dominantLabel(counts);
  const leadVal = leader === 'BUY' ? counts.buy : leader === 'SELL' ? counts.sell : counts.hold;
  const consensusPct = Math.round((leadVal / totalAgents) * 100);
  const roundLabel = roundLabelFrom(phase);

  const mem = Math.round(t.memMb ?? 0);
  const memCls = mem >= 90 ? 'crit' : mem >= 80 ? 'warn' : '';
  const slotsUsed = t.slotsUsed ?? 0;
  const slotsMax = t.slotsMax ?? 8;
  const tps = t.tps ?? 0;
  const elapsed = t.elapsedSeconds ?? 0;

  return (
    <div className="kpi-strip">
      <div className="kpi">
        <span className="kpi-label">Consensus</span>
        <span className="kpi-value">
          {leader}
          <small>{consensusPct}%</small>
        </span>
        <div className="composition">
          <div className="comp-buy"  style={{ flex: counts.buy  }}>{counts.buy}</div>
          <div className="comp-sell" style={{ flex: counts.sell }}>{counts.sell}</div>
          <div className="comp-hold" style={{ flex: counts.hold }}>{counts.hold}</div>
        </div>
      </div>
      <div className="kpi">
        <span className="kpi-label">Tokens / sec</span>
        <span className="kpi-value">{tps.toFixed(1)}<small>tps</small></span>
        <div className="spark">
          {Array.from({ length: 22 }).map((_, i) => {
            const h = 6 + ((i * 13 + Math.floor(tps)) % 16);
            return <span key={i} style={{ height: h }} className={i > 17 ? 'hi' : ''} />;
          })}
        </div>
      </div>
      <div className="kpi">
        <span className="kpi-label">Memory</span>
        {/* KR-41.1-04: memMb is a percentage — suffix literal "%" not "MB". */}
        <span className={`kpi-value ${memCls}`}>{mem}<small>%</small></span>
        <div className="kpi-bar">
          <span
            style={{
              width: `${Math.min(100, Math.max(0, mem))}%`,
              background: memCls === 'crit' ? 'var(--sell)' : memCls === 'warn' ? 'var(--accent)' : 'var(--buy)',
            }}
          />
        </div>
      </div>
      <div className="kpi">
        {/* KR-41.1-05: slotsUsed/slotsMax stubbed 0/8 by adapter until backend emits. */}
        <span className="kpi-label">Parallel slots</span>
        <span className="kpi-value">{slotsUsed}<small>/{slotsMax}</small></span>
        <div className="kpi-bar">
          <span style={{ width: `${(slotsUsed / Math.max(1, slotsMax)) * 100}%` }} />
        </div>
      </div>
      <div className="kpi">
        <span className="kpi-label">Elapsed · {roundLabel}/3</span>
        <span className="kpi-value">{formatElapsed(elapsed)}</span>
        <div className="kpi-bar">
          <span style={{ width: `${Math.min(100, (elapsed / 300) * 100)}%` }} />
        </div>
      </div>
    </div>
  );
}

// ── ConsensusRing ──────────────────────────────────────────────────────
// Subscribes to useAgents so the ring follows signal churn in lock-step
// with the force graph. Plan 02 exposes consensus as a scalar, but the
// design calls for a BUY/SELL/HOLD breakdown — derive it from agent
// signals we already have.
export function ConsensusRing() {
  const { agents } = useAgents();
  const counts = countSignals(agents);
  const total = Math.max(1, agents.length || counts.buy + counts.sell + counts.hold);
  const R = 48;
  const C = 2 * Math.PI * R;
  const buyLen = (counts.buy / total) * C;
  const sellLen = (counts.sell / total) * C;
  const holdLen = (counts.hold / total) * C;
  const leader = dominantLabel(counts);
  const leadVal = leader === 'BUY' ? counts.buy : leader === 'SELL' ? counts.sell : counts.hold;
  const leadPct = Math.round((leadVal / total) * 100);
  const leadColor = leader === 'BUY' ? 'var(--buy)' : leader === 'SELL' ? 'var(--sell)' : 'var(--hold)';
  return (
    <svg className="consensus-ring" viewBox="0 0 120 120">
      <circle cx="60" cy="60" r={R} fill="none" stroke="var(--border)" strokeWidth="8" />
      <g transform="rotate(-90 60 60)" fill="none" strokeWidth="8">
        <circle cx="60" cy="60" r={R} stroke="var(--buy)"  strokeDasharray={`${buyLen} ${C}`} />
        <circle cx="60" cy="60" r={R} stroke="var(--sell)" strokeDasharray={`${sellLen} ${C}`} strokeDashoffset={-buyLen} />
        <circle cx="60" cy="60" r={R} stroke="var(--hold)" strokeDasharray={`${holdLen} ${C}`} strokeDashoffset={-(buyLen + sellLen)} />
      </g>
      <text x="60" y="56" className="mid" fontSize="10" fill="var(--text-3)" letterSpacing="0.14em">CONSENSUS</text>
      <text x="60" y="72" className="mid" fontSize="18" fontWeight="700" fill={leadColor}>{leader}</text>
      <text x="60" y="86" className="mid" fontSize="10" fill="var(--text-2)">{leadPct}%</text>
    </svg>
  );
}
