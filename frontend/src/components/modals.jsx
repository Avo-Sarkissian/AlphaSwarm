// Modals: ShockDrawer + ReplayBar + CyclePickerModal — real-wired.
//
// Lifted from frontend-react-archive/src/components/modals.jsx (Phase 41.1 + 41.2
// per Plan 41.6-03 task 3). Pure JSX (no TS syntax) per codex HIGH-1 — file
// extension stays .jsx. The other modals from AlphaSwarm-2/src/modals.jsx
// (InterviewModal / ReportModal / AdvisoryModal) are NOT lifted in W3:
//   • InterviewModal — superseded by W4 InterviewV2 (D-11)
//   • ReportModal    — superseded by ./ReportModal.tsx (Phase 41.2 D-04 + D-20 rich)
//   • AdvisoryModal  — superseded by AdvisoryV2 in ./v2.tsx (D-08 / D-22)
import { useState, useEffect } from 'react';
import { Icon } from './icons';
import { simShock } from '../api/simulation';
import { listCycles, replayAdvance, replayStop } from '../api/replay';
import { ApiError } from '../api/client';
import { useConnection } from '../context/ConnectionContext';

// ─── Helpers ─────────────────────────────────────────────────────────────

function formatApiError(e) {
  if (e instanceof ApiError) {
    const detail =
      e.body && typeof e.body === 'object' && 'detail' in e.body
        ? e.body.detail
        : null;
    const message =
      typeof detail === 'string'
        ? detail
        : detail && typeof detail === 'object' && 'message' in detail
        ? detail.message
        : null;
    return message ? `HTTP ${e.status} — ${message}` : `HTTP ${e.status}`;
  }
  return String((e && e.message) || e || 'unknown error');
}

// ─── ShockDrawer ─────────────────────────────────────────────────────────
// Backend body: { shock_text: string }. The drawer builds the string from
// the selected preset / free-text input.

export function ShockDrawer({ onClose }) {
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const presets = [
    'DOJ files formal antitrust complaint',
    'Fed cuts 50bp at emergency session',
    'CEO denies acquisition talks publicly',
    'Treasury yields spike 40bp on inflation print',
  ];

  async function onInject() {
    const shockText = text.trim();
    if (!shockText || busy) return;
    setBusy(true);
    setErr(null);
    try {
      await simShock(shockText);
    } catch (e) {
      setErr(formatApiError(e));
      setBusy(false);
      return; // don't close on error — user can retry
    }
    setBusy(false);
    onClose();
  }

  return (
    <div className="shock-drawer">
      <div className="hflex" style={{ marginBottom: 10 }}>
        <Icon name="bolt" size={14} />
        <span className="label" style={{ color: 'var(--sell)' }}>
          Shock Injection · between rounds 2 &amp; 3
        </span>
        <div className="sp" />
        <button className="btn ghost" onClick={onClose}>
          <Icon name="close" />
        </button>
      </div>
      <div className="seed-input" style={{ marginBottom: 10 }}>
        <span className="prefix">⚡</span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Disruptive event text…"
          disabled={busy}
        />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
        {presets.map((p) => (
          <button
            key={p}
            className="btn ghost"
            style={{ fontSize: 10, height: 26 }}
            onClick={() => setText(p)}
            disabled={busy}
          >
            {p.length > 40 ? p.slice(0, 40) + '…' : p}
          </button>
        ))}
      </div>
      {err && (
        <div
          className="shock-error"
          style={{
            color: 'var(--sell)',
            fontSize: 11,
            marginBottom: 8,
            fontFamily: 'JetBrains Mono, monospace',
          }}
        >
          {err}
        </div>
      )}
      <div className="hflex">
        <span className="label">
          Impact preview · ~{Math.floor(20 + text.length * 0.7)} agents re-evaluate
        </span>
        <div className="sp" />
        <button className="btn" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button
          className="btn primary"
          onClick={onInject}
          disabled={busy || !text.trim()}
        >
          <Icon name="bolt" /> {busy ? 'Injecting…' : 'Inject'}
        </button>
      </div>
    </div>
  );
}

// ─── ReplayBar ───────────────────────────────────────────────────────────
// KR-41.1-06: Rewind disabled — backend exposes advance/stop only.

export function ReplayBar({ cycle, onExit }) {
  // Round comes from the frame's roundNum (Connection lastFrame) — phase is a
  // string ('replay'/'round_N'/'complete'), so Number(phase) was always NaN
  // and the progress track never moved. Fall back to 1 when unknown.
  const { lastFrame } = useConnection();
  const frameRound = lastFrame?.roundNum;
  const round =
    typeof frameRound === 'number' && frameRound >= 1
      ? Math.min(frameRound, 3)
      : lastFrame?.phase === 'complete'
      ? 3
      : 1;
  const [busy, setBusy] = useState(false);

  async function onForward() {
    if (busy) return;
    setBusy(true);
    try {
      await replayAdvance();
    } catch (e) {
      // KR-41.1-08: errors console.logged; structured error stream deferred.
      // eslint-disable-next-line no-console
      console.error('replay advance failed', e);
    } finally {
      setBusy(false);
    }
  }

  async function onExitReplay() {
    if (busy) return;
    setBusy(true);
    try {
      await replayStop();
    } catch (e) {
      // eslint-disable-next-line no-console
      console.error('replay stop failed', e);
    } finally {
      setBusy(false);
    }
    if (onExit) onExit();
  }

  return (
    <div className="replay-bar">
      <div className="label" style={{ color: 'var(--accent)' }}>
        <Icon name="replay" size={11} /> REPLAY · {cycle?.cycle_id ?? cycle?.id ?? ''}
      </div>
      {/* KR-41.1-06: Rewind disabled — no backend endpoint yet. */}
      <button
        className="btn ghost"
        disabled
        title="Rewind not supported (KR-41.1-06)"
      >
        <Icon name="rewind" />
      </button>
      <div className="replay-track">
        <div className="replay-fill" style={{ width: `${(round / 3) * 100}%` }} />
        <div className="replay-ticks">
          {['SEED', 'R1', 'R2', 'R3'].map((t, i) => (
            <span
              key={t}
              style={{ color: i <= round ? 'var(--accent)' : 'var(--text-3)' }}
            >
              {t}
            </span>
          ))}
        </div>
      </div>
      <button
        className="btn ghost"
        onClick={onForward}
        disabled={busy || round >= 3}
      >
        <Icon name="forward" />
      </button>
      <button className="btn" onClick={onExitReplay} disabled={busy}>
        Exit replay
      </button>
    </div>
  );
}

// ─── CyclePickerModal ────────────────────────────────────────────────────

export function CyclePickerModal({ onPick, onClose }) {
  const [cycles, setCycles] = useState(null); // null = loading
  const [err, setErr] = useState(null);

  useEffect(() => {
    let cancelled = false;
    listCycles()
      .then((cs) => {
        if (!cancelled) setCycles(cs);
      })
      .catch((e) => {
        if (cancelled) return;
        // KR-41.1-08: errors console.logged + surfaced to UI label.
        // eslint-disable-next-line no-console
        console.error('listCycles failed', e);
        setErr(e);
        setCycles([]);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="modal-backdrop" onClick={onClose}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ width: 'min(720px, 94%)' }}
      >
        <div className="modal-head">
          <Icon name="replay" />
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-2)',
            }}
          >
            SELECT CYCLE TO REPLAY
          </span>
          <div className="sp" />
          <button className="btn ghost" onClick={onClose}>
            <Icon name="close" />
          </button>
        </div>
        <div className="modal-body no-pad">
          {cycles === null && (
            <div style={{ padding: '30px 20px' }} className="label">
              Loading cycles…
            </div>
          )}
          {err && (
            <div
              style={{ padding: '30px 20px', color: 'var(--sell)' }}
              className="label"
            >
              {formatApiError(err)}
            </div>
          )}
          {cycles && cycles.length === 0 && !err && (
            <div style={{ padding: '30px 20px' }} className="label">
              No completed cycles yet.
            </div>
          )}
          {cycles &&
            cycles.map((c) => (
              <div
                key={c.cycle_id}
                style={{
                  padding: '14px 20px',
                  borderBottom: '1px solid var(--border)',
                  cursor: 'pointer',
                  display: 'grid',
                  gridTemplateColumns: '1fr auto auto',
                  gap: 18,
                  alignItems: 'center',
                }}
                onClick={async () => {
                  try {
                    // onPick may be async (app_v2 fires replayStart) — surface
                    // failures (e.g. 409 replay already active) in the existing
                    // err label instead of silently closing.
                    await onPick(c);
                  } catch (e) {
                    // KR-41.1-08: errors console.logged + surfaced to UI label.
                    // eslint-disable-next-line no-console
                    console.error('replay start failed', e);
                    setErr(e);
                  }
                }}
                onMouseOver={(e) => (e.currentTarget.style.background = 'var(--bg-3)')}
                onMouseOut={(e) => (e.currentTarget.style.background = 'transparent')}
              >
                <div>
                  <div
                    style={{ fontSize: 14, color: 'var(--text)', marginBottom: 4 }}
                  >
                    "{c.seed_rumor}"
                  </div>
                  <div className="label">{c.cycle_id}</div>
                </div>
                <div className="label">{c.created_at}</div>
                <div className="label">{c.round_count}R</div>
              </div>
            ))}
        </div>
      </div>
    </div>
  );
}
