// src/App.tsx — 7-context shell mirroring frontend-react-archive/src/App.tsx (docs/DECISIONS.md#p41-6-d-07)
// + onboarding localStorage gate skeleton (D-12).
// The full Onboarding component lands in Plan 41.6-04 (W4); this file just
// wires the gate so W2/W3 can run the dashboard against a flag-bypass.
//
// useWebSocket() runs ABOVE the gate so the WS
// connection is open for the entire session, even while Onboarding renders.
import { useState } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import type { ConnectionStatus } from './hooks/useWebSocket';
import { ConnectionProvider } from './context/ConnectionContext';
import { EdgesProvider } from './context/EdgesContext';
import { FrameProviders } from './context/FrameProviders';
import { App as DashboardShell } from './components/app_v2';
import { ConnectionBanner } from './components/ConnectionBanner';
import { Onboarding } from './components/onboarding';

const ONBOARDING_FLAG = 'as_onboarding_v1_complete';

export function App() {
  // useWebSocket() ABOVE the gate per Pitfall #6 — keeps WS open across onboarding.
  const { connected, status, lastFrame } = useWebSocket();

  // Onboarding gate (D-12). Full Onboarding component arrives in W4.
  // codex LOW-9 + gemini #6: derive initial state from BOTH the dev-skip env var
  // AND the persisted localStorage flag. Pure read; no localStorage writes during
  // the render path (no useEffect, no setItem in initializer).
  const [onboardingDone, setOnboardingDone] = useState<boolean>(() => {
    if (typeof window === 'undefined') return false;
    const devSkip = import.meta.env.DEV && import.meta.env.VITE_SKIP_ONBOARDING === 'true';
    const persisted = localStorage.getItem(ONBOARDING_FLAG) === 'true';
    return devSkip || persisted;
  });
  // codex LOW-9 + gemini #6 (preserved from W1 patch): the onboardingDone
  // initial state ALREADY honors VITE_SKIP_ONBOARDING=true via the useState
  // initializer above; the dev-skip path falls through to the dashboard render
  // automatically because onboardingDone === true at mount. We do NOT write
  // localStorage during render — the localStorage.setItem below runs only inside
  // the Onboarding onComplete event handler.
  if (!onboardingDone) {
    return (
      <Onboarding
        numRounds={lastFrame?.numRounds ?? null}
        onComplete={(_seed: string) => {
          // simStart was already fired inside Onboarding's Run handler — do NOT
          // re-fire here. We only persist the gate flag and unmount Onboarding.
          localStorage.setItem(ONBOARDING_FLAG, 'true');
          setOnboardingDone(true);
        }}
      />
    );
  }

  if (!lastFrame) {
    return (
      <ConnectionProvider connected={connected} status={status} lastFrame={null}>
        <AwaitingFrame status={status} />
      </ConnectionProvider>
    );
  }

  return (
    <FrameProviders frame={lastFrame} connected={connected} status={status}>
      <ConnectionBanner status={status} />
      <EdgesProvider>
        <DashboardShell />
      </EdgesProvider>
    </FrameProviders>
  );
}

function AwaitingFrame({ status }: { status: ConnectionStatus }) {
  const msg =
    status === 'open'
      ? 'Connected. Waiting for the first frame…'
      : status === 'connecting'
        ? 'Connecting to the backend…'
        : 'Backend not reachable on :8000. Retrying…';
  return (
    <div className="app awaiting-frame" role="status">
      {msg}
    </div>
  );
}
