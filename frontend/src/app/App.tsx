// App root: the context tree (docs/DECISIONS.md#p41-6-d-07) and the
// onboarding gate (docs/DECISIONS.md#p41-6-d-12).
//
// useWebSocket() runs ABOVE the gate so the WS
// connection is open for the entire session, even while Onboarding renders.
import { useState } from 'react';
import { useWebSocket } from '../hooks/useWebSocket';
import type { ConnectionStatus } from '../hooks/useWebSocket';
import { ConnectionProvider } from '../context/ConnectionContext';
import { EdgesProvider } from '../context/EdgesContext';
import { FrameProviders } from '../context/FrameProviders';
import { getDataSource } from '../data-source';
import { AppShell } from './AppShell';
import { ConnectionBanner } from './ConnectionBanner';
import { Onboarding } from '../features/onboarding/Onboarding';
import { awaitingMessage } from '../lib/awaitingMessage';
import { safeStorage } from '../lib/safeStorage';

const ONBOARDING_FLAG = 'as_onboarding_v1_complete';

export function App() {
  // useWebSocket() runs above the gate, so the socket stays open across onboarding.
  const { connected, status, lastFrame } = useWebSocket();

  // Onboarding gate (docs/DECISIONS.md#p41-6-d-12): derive the initial state
  // from BOTH the dev-skip env var
  // AND the persisted storage flag. Pure read; no storage writes during
  // the render path (no useEffect, no setItem in initializer).
  const [onboardingDone, setOnboardingDone] = useState<boolean>(() => {
    if (getDataSource().readOnly) return true;
    const devSkip = import.meta.env.DEV && import.meta.env.VITE_SKIP_ONBOARDING === 'true';
    return devSkip || safeStorage.get(ONBOARDING_FLAG) === 'true';
  });
  // The seed typed during onboarding pre-fills the dashboard, so the topbar
  // and SeedingState show what is actually running.
  const [initialSeed, setInitialSeed] = useState<string>('');
  // The onboardingDone initial state ALREADY honors VITE_SKIP_ONBOARDING=true via the useState
  // initializer above; the dev-skip path falls through to the dashboard render
  // automatically because onboardingDone === true at mount. We do NOT write
  // storage during render — the safeStorage.set below runs only inside
  // the Onboarding onComplete event handler.
  if (!onboardingDone) {
    return (
      <Onboarding
        numRounds={lastFrame?.numRounds ?? null}
        onComplete={(seed: string) => {
          // simStart was already fired inside Onboarding's Run handler — do NOT
          // re-fire here. Persist the gate flag, keep the seed, unmount Onboarding.
          safeStorage.set(ONBOARDING_FLAG, 'true');
          setInitialSeed(seed);
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
        <AppShell initialSeed={initialSeed} />
      </EdgesProvider>
    </FrameProviders>
  );
}

function AwaitingFrame({ status }: { status: ConnectionStatus }) {
  const msg = awaitingMessage(status, getDataSource().kind);
  return (
    <div className="app awaiting-frame" role="status">
      {msg}
    </div>
  );
}
