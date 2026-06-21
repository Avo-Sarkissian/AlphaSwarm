// RunConfirmModal — pre-run cost confirmation for CLOUD/MIXED inference runs.
//
// Rendered as a normal-flow overlay (modal-backdrop + modal pattern, matching
// CyclePickerModal and ComingSoonModal in this codebase).
//
// Props:
//   estimate   — RunEstimate from GET /api/settings/estimate, or null when the
//                estimate fetch failed (modal still renders with fallback copy).
//   onConfirm  — called when the user confirms the run.
//   onCancel   — called when the user cancels (no simStart invoked).
//   busy       — true while simStart is in flight after confirm.
//
// Estimate-unavailable UX: when estimate is null we show
// "estimate unavailable — run anyway?" so the user can still cancel a cloud run
// they did not intend to start. See useRunGate for full rationale.
import { Icon } from './icons';
import { RunEstimate } from '../api/settings';

export interface RunConfirmModalProps {
  estimate: RunEstimate | null;
  onConfirm: () => void;
  onCancel: () => void;
  busy: boolean;
}

export function RunConfirmModal({
  estimate,
  onConfirm,
  onCancel,
  busy,
}: RunConfirmModalProps) {
  const modeLabel =
    estimate === null
      ? 'Cloud / Mixed'
      : estimate.mode === 'mixed'
      ? 'Mixed (local + cloud)'
      : 'Cloud';

  return (
    <div className="modal-backdrop" onClick={busy ? undefined : onCancel}>
      <div
        className="modal"
        onClick={(e) => e.stopPropagation()}
        style={{ width: 'min(480px, 94%)' }}
      >
        <div className="modal-head">
          <Icon name="bolt" />
          <span
            style={{
              fontFamily: "'JetBrains Mono', monospace",
              fontSize: 11,
              letterSpacing: '0.12em',
              textTransform: 'uppercase',
              color: 'var(--text-2)',
            }}
          >
            Confirm cloud run
          </span>
          <div className="sp" />
          <button className="btn ghost" onClick={onCancel} disabled={busy}>
            <Icon name="close" />
          </button>
        </div>

        <div className="modal-body">
          {estimate === null ? (
            <p
              style={{
                color: 'var(--sell)',
                fontSize: 13,
                marginBottom: 16,
                lineHeight: 1.5,
              }}
            >
              Cost estimate unavailable — the estimate service could not be
              reached. This run will use cloud inference. Run anyway?
            </p>
          ) : (
            <div
              style={{
                display: 'grid',
                gridTemplateColumns: 'max-content 1fr',
                gap: '8px 16px',
                fontSize: 13,
                marginBottom: 16,
              }}
            >
              <span className="label">MODE</span>
              <span
                style={{
                  color: 'var(--accent)',
                  fontFamily: "'JetBrains Mono', monospace",
                  fontSize: 11,
                  letterSpacing: '0.08em',
                  textTransform: 'uppercase',
                  alignSelf: 'center',
                }}
              >
                {modeLabel}
              </span>

              <span className="label">CALLS</span>
              <span style={{ color: 'var(--text)', alignSelf: 'center' }}>
                ~{estimate.calls}
              </span>

              <span className="label">EST. COST</span>
              <span
                style={{
                  color: 'var(--text)',
                  fontFamily: "'JetBrains Mono', monospace",
                  alignSelf: 'center',
                }}
              >
                ${estimate.low_usd} – ${estimate.high_usd}
              </span>
            </div>
          )}

          <p
            style={{
              color: 'var(--text-3)',
              fontSize: 11,
              marginBottom: 0,
              lineHeight: 1.5,
            }}
          >
            This run will make cloud API calls that may incur charges on your
            provider account. Confirm only if you intend to proceed.
          </p>
        </div>

        <div
          className="hflex"
          style={{ padding: '10px 16px', borderTop: '1px solid var(--border)' }}
        >
          <div className="sp" />
          <button className="btn" onClick={onCancel} disabled={busy}>
            Cancel
          </button>
          <button
            className="btn primary"
            onClick={onConfirm}
            disabled={busy}
          >
            <Icon name="play" />
            {busy ? 'Starting…' : 'Confirm & run'}
          </button>
        </div>
      </div>
    </div>
  );
}
