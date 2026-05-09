// Tweaks panel — dev-only. Production mount goes through TweaksPanelLoader.tsx
// (React.lazy + import.meta.env.DEV gate) so this module's code never ships
// into dist/ in production (reviewer item 19).
//
// Plan 04 wiring:
//   • Consumes split contexts (useTelemetry + useAgents) — no useSnapshot.
//   • Holdings preview is dynamic-imported under import.meta.env.DEV only
//     (reviewer item 18). mocks/holdings is NEVER statically imported here.
//   • Dev-only "Force MemoryPaused" button dispatches a CustomEvent for
//     deterministic Plan 05 UAT coverage (reviewer item 23).
import { useEffect, useState } from 'react';
import { Icon } from './icons';
import { useTelemetry } from '../context/TelemetryContext';
import { useAgents } from '../context/AgentsContext';

export function TweaksPanel({ state, setState, onClose }) {
  const { layout, density, phase, sigMix } = state;
  const tel = useTelemetry();
  const agents = useAgents();

  const setMix = (key, val) => {
    const v = Math.max(0, Math.min(100, Number(val) || 0));
    setState((s) => ({ ...s, sigMix: { ...s.sigMix, [key]: v / 100 } }));
  };

  // Dev-only holdings fixture — dynamically imported so the mock never
  // reaches the production bundle. mocks/holdings is guarded by an
  // import.meta.env.DEV branch in a dynamic import() call.
  const [devHoldings, setDevHoldings] = useState([]);
  useEffect(() => {
    if (!import.meta.env.DEV) return;
    let cancelled = false;
    import('../mocks/holdings')
      .then((m) => {
        if (!cancelled) setDevHoldings(m.HOLDINGS ?? []);
      })
      .catch(() => {
        /* mocks not present in prod bundle — no-op */
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Dev-only deterministic memory-pause UAT hook (reviewer item 23).
  const forceMemPause = () => {
    window.dispatchEvent(new CustomEvent('as:force-mem-pause'));
  };

  return (
    <div className="tweaks-panel">
      <div className="tweaks-head">
        <div className="hflex">
          <Icon name="settings" />{' '}
          <span
            style={{
              fontFamily: 'JetBrains Mono',
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
            }}
          >
            Tweaks
          </span>
        </div>
        <button
          className="btn ghost"
          style={{ height: 24, padding: '0 6px' }}
          onClick={onClose}
        >
          <Icon name="close" />
        </button>
      </div>
      <div className="tweaks-body">
        <div className="tweak-group">
          <span className="tweak-label">Layout</span>
          <div className="seg">
            {[
              { k: 'force', label: 'Force' },
              { k: 'radial', label: 'Radial' },
              { k: 'grid', label: 'Grid' },
            ].map((l) => (
              <button
                key={l.k}
                data-active={layout === l.k}
                onClick={() => setState((s) => ({ ...s, layout: l.k }))}
              >
                {l.label}
              </button>
            ))}
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Density</span>
          <div className="seg">
            <button
              data-active={density === 'compact'}
              onClick={() => setState((s) => ({ ...s, density: 'compact' }))}
            >
              Compact
            </button>
            <button
              data-active={density === 'comfortable'}
              onClick={() =>
                setState((s) => ({ ...s, density: 'comfortable' }))
              }
            >
              Comfortable
            </button>
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Phase</span>
          <div className="seg">
            {['1', '2', '3', 'done'].map((p) => (
              <button
                key={p}
                data-active={String(phase) === p}
                onClick={() =>
                  setState((s) => ({
                    ...s,
                    phase: p === 'done' ? 'done' : Number(p),
                  }))
                }
              >
                {p === 'done' ? 'Final' : `R${p}`}
              </button>
            ))}
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Demo state</span>
          <div className="seg seg-wrap">
            {[
              { k: 'live', label: 'Live' },
              { k: 'idle', label: 'Idle' },
              { k: 'seeding', label: 'Seeding' },
              { k: 'mempause', label: 'Mem ceiling' },
              { k: 'error', label: 'Error' },
            ].map((o) => (
              <button
                key={o.k}
                data-active={(state.demoState || 'live') === o.k}
                onClick={() =>
                  setState((s) => ({ ...s, demoState: o.k }))
                }
              >
                {o.label}
              </button>
            ))}
          </div>
        </div>

        <div className="tweak-group">
          <span className="tweak-label">Signal distribution</span>
          <div className="sig-mix">
            <label>
              <span className="buy">BUY %</span>
              <input
                type="number"
                min="0"
                max="100"
                value={Math.round(sigMix.buy * 100)}
                onChange={(e) => setMix('buy', e.target.value)}
              />
            </label>
            <label>
              <span className="sell">SELL %</span>
              <input
                type="number"
                min="0"
                max="100"
                value={Math.round(sigMix.sell * 100)}
                onChange={(e) => setMix('sell', e.target.value)}
              />
            </label>
            <label>
              <span className="hold">HOLD %</span>
              <input
                type="number"
                min="0"
                max="100"
                value={Math.round(sigMix.hold * 100)}
                onChange={(e) => setMix('hold', e.target.value)}
              />
            </label>
          </div>
          <div
            style={{
              fontSize: 10,
              color: 'var(--text-3)',
              fontFamily: 'JetBrains Mono',
              marginTop: 4,
            }}
          >
            Normalized automatically. Bracket biases applied on top.
          </div>
        </div>

        {/* Live telemetry preview — confirms split-context wiring. */}
        <div className="tweak-group">
          <span className="tweak-label">Live telemetry</span>
          <div
            className="mono"
            style={{ fontSize: 10, color: 'var(--text-3)', lineHeight: 1.6 }}
          >
            <div>
              phase: <span style={{ color: 'var(--text-2)' }}>{tel.phase}</span>
            </div>
            <div>
              running:{' '}
              <span style={{ color: 'var(--text-2)' }}>
                {String(tel.running)}
              </span>
            </div>
            <div>
              agents:{' '}
              <span style={{ color: 'var(--text-2)' }}>
                {agents.agents.length}
              </span>
            </div>
            <div>
              mem%:{' '}
              <span style={{ color: 'var(--text-2)' }}>
                {tel.telemetry?.memMb ?? 0}
              </span>
            </div>
          </div>
        </div>

        {/* Dev-only deterministic UAT hook (reviewer item 23 — Plan 05). */}
        <div className="tweak-group">
          <span className="tweak-label">Dev controls</span>
          <button
            className="btn ghost"
            style={{ fontSize: 10, height: 26 }}
            onClick={forceMemPause}
          >
            Force MemoryPaused (dev)
          </button>
        </div>

        {/* Dev holdings preview — dynamic import only. */}
        {devHoldings.length > 0 && (
          <div className="tweak-group">
            <span className="tweak-label">Dev holdings preview</span>
            <div
              className="mono"
              style={{
                fontSize: 10,
                color: 'var(--text-3)',
                lineHeight: 1.6,
              }}
            >
              {devHoldings.map((h) => (
                <div key={h.ticker}>
                  {h.ticker} · {h.shares}sh · basis ${h.basis}
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
