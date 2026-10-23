// Model status chip: inference mode and spend from /api/health next to live run telemetry.
import { getHealth } from '../../api/settings';
import { useTelemetry } from '../../context/TelemetryContext';
import { useConnection } from '../../context/ConnectionContext';
import { useRounds } from '../../hooks/useRounds';
import { usePolling } from '../../hooks/usePolling';

// Polls GET /api/health at 10s intervals for inference_mode and
// spent_usd. Until health answers it says "Checking…", and "Mode unknown" when
// the request fails, never a guessed "Local". inference_mode looks at providers
// only, so an Ollama cloud model still reads as Local here while Settings, which
// applies the advisory's off-machine rule, says local + cloud.
export function ModelStatus() {
  const tel = useTelemetry();
  const conn = useConnection();
  const running = conn.lastFrame !== null && tel.running;
  const phase = tel.phase;
  const tps = tel.telemetry.tps ?? 0;
  const slots = tel.telemetry.slotsUsed ?? 0;
  // Round and depth come from the frame (roundNum, num_rounds), never from the phase string.
  const roundNum = conn.lastFrame?.roundNum ?? null;
  const { numRounds } = useRounds();

  // Live inference mode from /api/health — poll every 10 s.
  const { data: healthData, error: healthError } = usePolling({
    key: 'health-inference-mode',
    fetchFn: getHealth,
    intervalMs: 10_000,
  });
  const inferenceMode = healthData?.inference_mode ?? null;
  const spentUsd = healthData?.spent_usd ?? null;

  // Derive a human-readable mode label from the inference_mode field.
  function modeLabel(mode: 'local' | 'cloud' | 'mixed' | null): string {
    if (mode === 'local') return 'Local';
    if (mode === 'cloud') return 'Cloud';
    if (mode === 'mixed') return 'Mixed';
    return healthError !== null ? 'Mode unknown' : 'Checking…';
  }

  const ops = [
    `${
      phase === 'complete'
        ? 'complete'
        : phase === 'idle'
          ? 'idle'
          : roundNum != null && roundNum >= 1
            ? `round ${roundNum}/${numRounds}`
            : phase // 'seeding' / pre-round frames have no round yet
    }`,
    `${slots} slots`,
    `${tps.toFixed(1)} t/s`,
  ];

  const modeParts = [modeLabel(inferenceMode)];
  if (spentUsd !== null && spentUsd > 0) {
    modeParts.push(`$${spentUsd.toFixed(2)}`);
  }

  return (
    <div className="model-status" data-running={running}>
      <div className="ms-model">
        <span className="ms-dot" data-running={running} />
        <span className="mono ms-name">{modeParts.join(' · ')}</span>
      </div>
      <div className="ms-ops">
        {ops.map((o, i) => (
          <span key={i} className="ms-op">
            {o}
          </span>
        ))}
      </div>
    </div>
  );
}
