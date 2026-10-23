import type { ConnectionStatus } from '../hooks/useWebSocket';

/** Global notice while the live channel is stalled or reconnecting. */
export function ConnectionBanner({ status }: { status: ConnectionStatus }) {
  if (status === 'open' || status === 'connecting') return null;
  const text =
    status === 'stale'
      ? 'No update from the backend for 2 s. Showing the last frame; reconnecting at 5 s.'
      : 'Connection to the backend lost. Reconnecting…';
  return (
    <div className="connection-banner" role="status" aria-live="polite" data-status={status}>
      {text}
    </div>
  );
}
