import { useTelemetry } from '../context/TelemetryContext';
import { useAgents } from '../context/AgentsContext';
import { useConnection } from '../context/ConnectionContext';

export type OverlayKind = 'idle' | 'seeding' | 'mempause' | 'error' | null;

// Derives which full-canvas overlay to show (or null = live graph).
// Decision table matches states.jsx LifecycleOverlay — extracted here so
// downstream components can read the kind without mounting the overlay.
export function useLifecycleOverlay(memThresholdPct = 90): OverlayKind {
  const tel = useTelemetry();
  const conn = useConnection();
  const { agents } = useAgents();

  if (conn.reconnectFailed) return 'error';
  const phase = tel.phase;
  if (phase === 'idle') return 'idle';
  if (phase === 'seeding') return 'seeding';
  if (phase === 'round_1' && agents.length < 100) return 'seeding';
  const memPct = tel.telemetry?.memMb ?? 0;
  if (memPct >= memThresholdPct) return 'mempause';
  return null;
}
