import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { formatApiError } from '../../lib/apiError';
import { extractErrorDetail } from '../../lib/settingsForm';

describe('extractErrorDetail', () => {
  it('keeps the settings-specific 409 message', () => {
    const err = new ApiError(409, { detail: { error: 'simulation_running', message: 'A simulation is running' } }, '/api/settings');
    expect(extractErrorDetail(err)).toBe('Stop the running simulation first.');
  });

  it('formats a code-only envelope like the rest of the app instead of dumping JSON', () => {
    const err = new ApiError(503, { detail: { error: 'graph_unavailable' } }, '/api/settings/test');
    expect(extractErrorDetail(err)).toBe('graph unavailable (HTTP 503)');
    expect(extractErrorDetail(err)).toBe(formatApiError(err));
  });

  it('shows a timeout as text, not "Error 0"', () => {
    const err = new ApiError(0, null, '/api/settings', 'No response from /api/settings after 30 s', 'timeout');
    expect(extractErrorDetail(err)).toBe('No response from /api/settings after 30 s');
  });

  it('formats plain errors like the rest of the app', () => {
    const err = new Error('network down');
    expect(extractErrorDetail(err)).toBe(formatApiError(err));
  });
});
