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

if (import.meta.env.DEV) {
  // Side-effect import: eagerly pulls every ported JSX component through the
  // smoke harness so tsc + Vite type-check + bundle them even though the
  // AppShell does not mount them yet.
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
        <AppShell placeholder />
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
                <AppShell />
              </EdgesProvider>
            </RationalesProvider>
          </BracketProvider>
        </AgentsProvider>
      </TelemetryProvider>
    </ConnectionProvider>
  );
}

function AppShell({ placeholder }: { placeholder?: boolean }) {
  return (
    <div
      style={{
        padding: 24,
        fontFamily:
          'ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif',
      }}
    >
      <h1>
        AlphaSwarm — Wave 1 scaffold
        {placeholder ? ' (awaiting WebSocket)' : ''}
      </h1>
      <p>Providers mounted. Plans 03 and 04 wire dashboard surfaces.</p>
    </div>
  );
}
