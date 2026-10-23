// Dashboard shell: topbar, banners, the dashboard grid, the replay bar and the
// single overlay slot (docs/DECISIONS.md#adr-frontend-quant-terminal).
import { useCallback, useEffect, useState } from 'react';
import { simStop } from '../api/simulation';
import { InlineError } from '../components/InlineError';
import { useFrameMeta } from '../context/FrameMetaContext';
import { useTelemetry } from '../context/TelemetryContext';
import { Dashboard } from '../features/dashboard/Dashboard';
import { ReplayBar } from '../features/dashboard/ReplayBar';
import { RunErrorBanner } from '../features/dashboard/RunErrorBanner';
import { SignalWire } from '../features/wire/SignalWire';
import { useAwaitRunFrame } from '../hooks/useAwaitRunFrame';
import { useRound, useRounds } from '../hooks/useRounds';
import { useRunGate } from '../hooks/useRunGate';
import { formatApiError } from '../lib/apiError';
import { lifecycleOf } from '../lib/lifecycle';
import { phaseLabelFor } from '../lib/phase';
import { ModalHost, type ActiveModal } from './ModalHost';
import { RunControls } from './RunControls';
import { Topbar } from './Topbar';

export function AppShell({ initialSeed = '' }: { initialSeed?: string }) {
  const tel = useTelemetry();
  const lifecycle = lifecycleOf(useFrameMeta());
  const phase = tel.phase;
  const memMb = tel.telemetry.memMb;
  // Governor-driven paused/crisis warning: the backend governor pauses and
  // resumes on its own, so the UI only warns; it never restarts the simulation.
  const governorState = tel.telemetry.governorState;
  const governorPaused = governorState === 'paused' || governorState === 'crisis';
  const [govBannerDismissed, setGovBannerDismissed] = useState(false);
  useEffect(() => {
    if (!governorPaused) setGovBannerDismissed(false); // re-arm after recovery
  }, [governorPaused]);

  const [seed, setSeed] = useState<string>(initialSeed);
  const [actionError, setActionError] = useState<string | null>(null);
  const [modal, setModal] = useState<ActiveModal>({ kind: 'none' });
  const closeModal = useCallback(() => setModal({ kind: 'none' }), []);
  const openInterview = (agentId: string) => setModal({ kind: 'interview', agentId });

  // Round on screen from the frame (useRound), never parsed from the phase
  // string, so replay and 2-round runs label correctly (lib/phase.ts).
  const { numRounds } = useRounds();
  const currentRound = useRound();
  const phaseLabel = phaseLabelFor(phase, currentRound, numRounds);
  const phaseState: 'live' | 'complete' = phase === 'complete' ? 'complete' : 'live';

  // Run gate: cost confirmation for cloud/mixed runs, then simStart. It keeps
  // the failure message and a pending flag for the Run control. After an
  // accepted start, Run stays on "Starting…" until the run reaches the frame.
  const runStart = useAwaitRunFrame(lifecycle);
  const runGate = useRunGate({
    onSettled: (ok) => {
      if (ok) runStart.arm();
    },
  });
  const runConfirmModal = runGate.modal;
  // A run that reached SEEDING supersedes an earlier Run error, such as the
  // 409 a second tab got.
  const { clearError: clearRunError } = runGate;
  useEffect(() => {
    if (lifecycle === 'seeding') clearRunError();
  }, [lifecycle, clearRunError]);
  const onRun = () => runGate.requestRun(seed.trim());
  const onStop = async () => {
    setActionError(null);
    try {
      await simStop();
    } catch (err) {
      setActionError(formatApiError(err));
    }
  };

  const runControls = (
    <RunControls
      seed={seed}
      pending={runGate.pending || runStart.awaiting}
      onRun={onRun}
      onStop={() => void onStop()}
    />
  );

  // Dismissible banner, not a takeover: the backend governor throttles and
  // resumes on its own, so there is no resume button.
  const governorBanner = governorPaused && !govBannerDismissed && (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: 12, padding: '7px 14px',
        background: 'color-mix(in srgb, var(--sell) 10%, var(--bg-2))',
        borderBottom: '1px solid color-mix(in srgb, var(--sell) 35%, transparent)',
      }}
    >
      <span className="label" style={{ color: 'var(--sell)' }}>
        GOVERNOR {governorState?.toUpperCase()} · MEMORY {Math.round(memMb)}%
      </span>
      <span style={{ color: 'var(--text-2)', fontSize: 11 }}>
        Inference throttled under memory pressure — the governor resumes
        automatically once pressure clears. No action needed.
      </span>
      <div style={{ flex: 1 }} />
      <button
        className="btn ghost"
        style={{ height: 22, padding: '0 8px' }}
        onClick={() => setGovBannerDismissed(true)}
      >
        Dismiss
      </button>
    </div>
  );

  return (
    <div className="app" data-dir="a" data-density="comfortable" data-screen-label="01 Dashboard">
      <Topbar
        phaseLabel={phaseLabel}
        phaseState={phaseState}
        seed={seed}
        onSeedChange={setSeed}
        runControls={runControls}
        onOpen={setModal}
        onToggleShock={() => setModal((m) => (m.kind === 'shock' ? { kind: 'none' } : { kind: 'shock' }))}
      />

      <InlineError error={runGate.error} onDismiss={runGate.clearError} />
      <InlineError error={actionError} onDismiss={() => setActionError(null)} />
      <RunErrorBanner />

      {/* Signal Wire ticker — live data_source_audit slice (docs/DECISIONS.md#kr-41-1-02) */}
      <SignalWire onInspect={() => setModal({ kind: 'dataSources' })} />
      {governorBanner}

      <Dashboard
        seed={seed}
        onInterview={openInterview}
        onOpenBracket={(row) => setModal({ kind: 'bracket', bracket: row })}
        onShowCycles={() => setModal({ kind: 'cycles' })}
      />

      <ModalHost modal={modal} onOpen={setModal} onClose={closeModal} />
      {/* Replay is driven by the frame (mode), so the bar survives a reload. */}
      {lifecycle === 'replay' && <ReplayBar />}

      {/* Pre-run cost confirmation modal (cloud/mixed mode only). */}
      {runConfirmModal}
    </div>
  );
}
