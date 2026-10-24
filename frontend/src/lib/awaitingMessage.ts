// What the page says before its first frame, for the live backend and the static demo.
import type { ConnectionStatus } from '../data-source';

export function awaitingMessage(status: ConnectionStatus, kind: 'live' | 'demo'): string {
  if (kind === 'demo') {
    return status === 'closed'
      ? 'The demo data could not be loaded. Reload the page to try again.'
      : 'Loading the recorded cycle…';
  }
  if (status === 'open') return 'Connected. Waiting for the first frame…';
  if (status === 'connecting') return 'Connecting to the backend…';
  return 'Backend not reachable on :8000. Retrying…';
}
