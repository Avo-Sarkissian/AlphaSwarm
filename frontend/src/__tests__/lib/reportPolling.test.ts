import { describe, expect, it } from 'vitest';
import { shouldKeepPolling } from '../../lib/reportPolling';

describe('shouldKeepPolling', () => {
  it('keeps polling only while the report job runs', () => {
    expect(shouldKeepPolling({ status: 409, code: 'report_generation_in_progress' })).toBe(true);
  });

  it.each([
    { status: 404, code: 'report_not_found' },
    { status: 500, code: 'report_generation_failed' },
    { status: 409, code: 'advisory_generation_in_progress' },
    { status: 422, code: 'cycle_not_ready' },
    { status: 409, code: null },
  ])('stops for %j', (detail) => {
    expect(shouldKeepPolling(detail)).toBe(false);
  });
});
