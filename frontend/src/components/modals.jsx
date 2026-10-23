// Modals: ShockDrawer + ReplayBar — real-wired.
//
// Lifted from frontend-react-archive/src/components/modals.jsx (Phase 41.1 + 41.2
// per Plan 41.6-03 task 3). Pure JSX (no TS syntax) per codex HIGH-1 — file
// extension stays .jsx. The other modals from AlphaSwarm-2/src/modals.jsx
// (InterviewModal / ReportModal / AdvisoryModal) are NOT lifted in W3:
//   • InterviewModal — superseded by W4 InterviewV2 (D-11)
//   • ReportModal    — superseded by ./ReportModal.tsx (Phase 41.2 D-04 + D-20 rich)
//   • AdvisoryModal  — superseded by AdvisoryV2 in ./v2.tsx (D-08 / D-22)
import { useState } from 'react';
import { Icon } from './icons';
import { simShock } from '../api/simulation';
import { replayAdvance, replayStop } from '../api/replay';
import { useConnection } from '../context/ConnectionContext';
import { useFrameMeta } from '../context/FrameMetaContext';
import { useRounds } from '../hooks/useRounds';
import { formatApiError } from '../lib/apiError';
import { SHOCK_MAX_CHARS, SHOCK_MIN_CHARS, shockLengthError, shockTargetRound } from '../lib/shock';
import { InlineError } from './InlineError';

// ─── ShockDrawer ─────────────────────────────────────────────────────────
// POST /api/simulate/shock { shock_text }. Open only while a later gated
// round is left; length limits mirror the backend ShockText (lib/shock.ts).

export function ShockDrawer({ onClose }) {
  const { lastFrame } = useConnection();
  const windowOpen = lastFrame?.shockWindowOpen ?? false;
  const pending = lastFrame?.pendingShock ?? null;
  // round_num still holds the previous run's last round while seeding (docs/DECISIONS.md#b1).
  const roundNum = lastFrame?.phase === 'seeding' ? null : lastFrame?.roundNum ?? null;
  const target = shockTargetRound(roundNum, lastFrame?.numRounds ?? 0, windowOpen);
  const [text, setText] = useState('');
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  const closed = target === null;
  const trimmed = text.trim();
  const lengthError = shockLengthError(text);
  const canInject =
    !closed && pending === null && !busy && trimmed.length >= SHOCK_MIN_CHARS && lengthError === null;

  const presets = [
    'DOJ files formal antitrust complaint',
    'Fed cuts 50bp at emergency session',
    'CEO denies acquisition talks publicly',
    'Treasury yields spike 40bp on inflation print',
  ];

  async function onInject() {
    if (!canInject) return;
    setBusy(true);
    setErr(null);
    try {
      await simShock(trimmed);
    } catch (e) {
      setErr(formatApiError(e));
      setBusy(false);
      return; // stay open so the user sees why
    }
    setBusy(false);
    onClose();
  }

  const label = closed
    ? 'Shock injection · window closed: no later round left to reach'
    : `Shock injection · lands before round ${target} and stays active after`;

  return (
    <div className="shock-drawer">
      <div className="hflex" style={{ marginBottom: 10 }}>
        <Icon name="bolt" size={14} />
        <span className="label" style={{ color: 'var(--sell)' }}>{label}</span>
        <div className="sp" />
        <button className="btn ghost" onClick={onClose} aria-label="Close shock drawer">
          <Icon name="close" />
        </button>
      </div>
      {pending && (
        <div className="label" style={{ marginBottom: 10, color: 'var(--accent)' }}>
          Queued for the next round: "{pending}"
        </div>
      )}
      <div className="seed-input" style={{ marginBottom: 10 }}>
        <span className="prefix">⚡</span>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          placeholder="Disruptive event text…"
          maxLength={SHOCK_MAX_CHARS}
          disabled={busy || closed}
        />
      </div>
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6, marginBottom: 12 }}>
        {presets.map((p) => (
          <button
            key={p}
            className="btn ghost"
            style={{ fontSize: 10, height: 26 }}
            onClick={() => setText(p)}
            disabled={busy || closed}
          >
            {p}
          </button>
        ))}
      </div>
      {err && (
        <div className="shock-error" role="alert" style={{ color: 'var(--sell)', fontSize: 11, marginBottom: 8 }}>
          {err}
        </div>
      )}
      <div className="hflex">
        <span className="label">{lengthError ?? `${trimmed.length}/${SHOCK_MAX_CHARS}`}</span>
        <div className="sp" />
        <button className="btn" onClick={onClose} disabled={busy}>
          Cancel
        </button>
        <button className="btn primary" onClick={onInject} disabled={!canInject}>
          <Icon name="bolt" /> {busy ? 'Injecting…' : 'Inject'}
        </button>
      </div>
    </div>
  );
}

// ─── ReplayBar ───────────────────────────────────────────────────────────
// Driven entirely by the frame (mode === 'replay' decides whether the app
// mounts it), so it survives a page reload: the backend replay is the source
// of truth, not local UI state. Forward and exit only; there is no rewind
// endpoint (docs/DECISIONS.md#kr-41-1-06).
export function ReplayBar() {
  const { cycleId } = useFrameMeta();
  const { rounds, numRounds, currentRound } = useRounds();
  const round = currentRound ?? 1;
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState(null);

  async function run(action) {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await action();
    } catch (e) {
      setErr(formatApiError(e));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="replay-bar">
      <div className="label" style={{ color: 'var(--accent)' }}>
        <Icon name="replay" size={11} /> REPLAY · {cycleId ?? ''}
      </div>
      <div className="replay-track">
        <div className="replay-fill" style={{ width: `${(round / numRounds) * 100}%` }} />
        <div className="replay-ticks">
          {['SEED', ...rounds.map((r) => `R${r}`)].map((t, i) => (
            <span key={t} style={{ color: i <= round ? 'var(--accent)' : 'var(--text-3)' }}>
              {t}
            </span>
          ))}
        </div>
      </div>
      <button
        className="btn ghost"
        aria-label="Next round"
        onClick={() => run(replayAdvance)}
        disabled={busy || round >= numRounds}
      >
        <Icon name="forward" />
      </button>
      <button className="btn" onClick={() => run(replayStop)} disabled={busy}>
        Exit replay
      </button>
      <InlineError error={err} onDismiss={() => setErr(null)} />
    </div>
  );
}
