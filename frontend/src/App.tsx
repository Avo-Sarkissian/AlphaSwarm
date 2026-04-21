// Plan 02 Task 3: assemble the 6-context provider tree around AppShell.
//
// useWebSocket owns the /ws/state connection (3-retry backoff + defensive
// JSON.parse + adaptSnapshot). Its `lastFrame` is the most recent CONTRACT
// StateFrame (null until first message arrives). Until we have a frame, we
// still mount ConnectionProvider so banners/placeholder UI can read connected
// + reconnectFailed. Once a frame is present, the 4 frame-driven providers
// (Telemetry/Agents/Bracket/Rationales) mount and EdgesProvider nests beneath
// them (it needs `round` to drive /api/edges fetching via useCurrentCycle).
//
// DEV-only `_smoke` side-effect import is kept from Task 1.5 so tsc + Vite
// continue to type-check every ported JSX file even though AppShell does not
// mount them yet — Plans 03/04 will replace AppShell body.
import { useWebSocket } from './hooks/useWebSocket';
import { ConnectionProvider } from './context/ConnectionContext';
import { TelemetryProvider } from './context/TelemetryContext';
import { AgentsProvider } from './context/AgentsContext';
import { BracketProvider } from './context/BracketContext';
import { RationalesProvider } from './context/RationalesContext';
import { EdgesProvider } from './context/EdgesContext';
import { App as DashboardShell } from './components/app_v2';

if (import.meta.env.DEV) {
  void import('./_smoke');
}

export function App() {
  const { connected, reconnectFailed, lastFrame } = useWebSocket();
  const round = lastFrame?.roundNum ?? null;

  if (!lastFrame) {
    return (
      <ConnectionProvider
        connected={connected}
        reconnectFailed={reconnectFailed}
        lastFrame={null}
      >
        <AwaitingFrame connected={connected} reconnectFailed={reconnectFailed} />
      </ConnectionProvider>
    );
  }

  return (
    <ConnectionProvider
      connected={connected}
      reconnectFailed={reconnectFailed}
      lastFrame={lastFrame}
    >
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

function AwaitingFrame({
  connected,
  reconnectFailed,
}: {
  connected: boolean;
  reconnectFailed: boolean;
}) {
  const msg = reconnectFailed
    ? 'WebSocket disconnected — check backend on :8000'
    : connected
    ? 'Connected — waiting for first simulation frame…'
    : 'Connecting to WebSocket…';
  return (
    <div
      className="app"
      style={{
        width: '100%',
        height: '100%',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg)',
        color: 'var(--text-2)',
        fontFamily: "'JetBrains Mono', monospace",
        fontSize: 12,
        letterSpacing: '0.08em',
      }}
    >
      {msg}
    </div>
  );
}
