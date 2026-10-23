// Dashboard banner for the frame's last_error. The message is
// backend-templated and never contains paths or keys (alphaswarm.errors.RunError); the backend
// clears it when the next run starts. Dismiss hides this error only.
import { useState } from 'react';
import { useConnection } from '../../context/ConnectionContext';

export function RunErrorBanner() {
  const { lastFrame } = useConnection();
  const error = lastFrame?.lastError ?? null;
  const [dismissedTs, setDismissedTs] = useState<number | null>(null);
  if (error === null || error.ts === dismissedTs) return null;
  return (
    <div className="run-error-banner" role="alert">
      <span className="label run-error-title">
        RUN FAILED{error.roundNum !== null ? ` · ROUND ${error.roundNum}` : ''}
      </span>
      <span className="run-error-message">{error.message}</span>
      <span className="run-error-code mono">{error.code}</span>
      <div style={{ flex: 1 }} />
      <button type="button" className="btn ghost" onClick={() => setDismissedTs(error.ts)}>
        Dismiss
      </button>
    </div>
  );
}
