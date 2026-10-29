import { describe, expect, it } from 'vitest';
import { awaitingMessage } from '../../lib/awaitingMessage';

describe('awaitingMessage', () => {
  it.each([
    ['connecting', 'Connecting to the backend…'],
    ['open', 'Connected. Waiting for the first frame…'],
    ['closed', 'Backend not reachable on :8000. Retrying…'],
  ] as const)('live %s', (status, text) => {
    expect(awaitingMessage(status, 'live')).toBe(text);
  });

  it('tells a demo visitor what is loading and when it failed', () => {
    expect(awaitingMessage('connecting', 'demo')).toBe('Loading the recorded cycle…');
    expect(awaitingMessage('closed', 'demo')).toBe('The demo data could not be loaded. Reload the page to try again.');
  });
});
