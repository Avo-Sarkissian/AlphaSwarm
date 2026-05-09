// src/App.tsx — 6-context shell mirroring frontend-react-archive/src/App.tsx (D-07)
// + onboarding localStorage gate skeleton (D-12).
// The full Onboarding component lands in Plan 41.6-04 (W4); this file just
// wires the gate so W2/W3 can run the dashboard against a flag-bypass.
//
// Pitfall #6 (RESEARCH.md): useWebSocket() runs ABOVE the gate so the WS
// connection is open for the entire session, even while Onboarding renders.
import { useState } from 'react';
import { useWebSocket } from './hooks/useWebSocket';
import { ConnectionProvider } from './context/ConnectionContext';
import { TelemetryProvider } from './context/TelemetryContext';
import { AgentsProvider } from './context/AgentsContext';
import { BracketProvider } from './context/BracketContext';
import { RationalesProvider } from './context/RationalesContext';
import { EdgesProvider } from './context/EdgesContext';
import { App as DashboardShell } from './components/app_v2';

const ONBOARDING_FLAG = 'as_onboarding_v1_complete';

export function App() {
  // useWebSocket() ABOVE the gate per Pitfall #6 — keeps WS open across onboarding.
  const { connected, reconnectFailed, lastFrame } = useWebSocket();
  const round = lastFrame?.roundNum ?? null;

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
  // W1 SHIM rationale: when VITE_SKIP_ONBOARDING=true is set in dev (typically via
  // .env.local), the initializer above already sets onboardingDone=true so we fall
  // straight through to the dashboard render. NO localStorage write happens during
  // render — the dev-skip path is purely an in-memory bypass; the persisted flag
  // is only set when the human clicks "Continue" below.
  // W4 Plan 41.6-04 replaces this stub with `<Onboarding onComplete={...} />`.
  if (!onboardingDone) {
    return (
      <div className="onboarding-stub" style={{
        padding: 24, fontFamily: 'monospace', color: 'var(--text-2)',
        display: 'flex', flexDirection: 'column', gap: 12, alignItems: 'flex-start'
      }}>
        <div>Onboarding flow lands in Plan 41.6-04 (W4).</div>
        <button
          onClick={() => {
            localStorage.setItem(ONBOARDING_FLAG, 'true');
            setOnboardingDone(true);
          }}
          style={{ padding: '6px 12px', cursor: 'pointer' }}
        >
          Continue (W1 stub)
        </button>
      </div>
    );
  }

  if (!lastFrame) {
    return (
      <ConnectionProvider connected={connected} reconnectFailed={reconnectFailed} lastFrame={null}>
        <AwaitingFrame connected={connected} reconnectFailed={reconnectFailed} />
      </ConnectionProvider>
    );
  }

  return (
    <ConnectionProvider connected={connected} reconnectFailed={reconnectFailed} lastFrame={lastFrame}>
      <TelemetryProvider frame={lastFrame}>
        <AgentsProvider frame={lastFrame}>
          <BracketProvider frame={lastFrame}>
            <RationalesProvider frame={lastFrame}>
              <EdgesProvider round={round}>
                <DashboardShell />
              </EdgesProvider>
            </RationalesProvider>
          </BracketProvider>
        </AgentsProvider>
      </TelemetryProvider>
    </ConnectionProvider>
  );
}

function AwaitingFrame({ connected, reconnectFailed }: { connected: boolean; reconnectFailed: boolean }) {
  const msg = reconnectFailed
    ? 'WebSocket disconnected — check backend on :8000'
    : connected
    ? 'Connected — waiting for first simulation frame…'
    : 'Connecting to WebSocket…';
  return (
    <div className="app" style={{
      width: '100%', height: '100%', display: 'flex', alignItems: 'center',
      justifyContent: 'center', background: 'var(--bg)', color: 'var(--text-2)',
      fontFamily: "'JetBrains Mono', monospace", fontSize: 12, letterSpacing: '0.08em'
    }}>{msg}</div>
  );
}
