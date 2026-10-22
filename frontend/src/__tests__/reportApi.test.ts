import { afterEach, describe, expect, it, vi } from 'vitest';
import { ApiError } from '../api/client';
import { advisoryFetch } from '../api/advisory';
import { reportFetch, reportPoll } from '../api/report';

const CYCLE = '00000000-0000-4000-8000-0000000000a1';

function respond(status: number, body: unknown): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(JSON.stringify(body), {
        status,
        headers: { 'content-type': 'application/json' },
      }),
    ),
  );
}

const envelope = (error: string, message = 'm') => ({ detail: { error, message } });

afterEach(() => {
  vi.unstubAllGlobals();
});

describe('reportPoll', () => {
  it('returns the report on 200', async () => {
    respond(200, { cycle_id: CYCLE, content: '# R', generated_at: 't' });
    await expect(reportPoll(CYCLE)).resolves.toMatchObject({ content: '# R' });
  });

  it('returns null (keep polling) while the job runs', async () => {
    respond(409, envelope('report_generation_in_progress'));
    await expect(reportPoll(CYCLE)).resolves.toBeNull();
  });

  it.each([
    [404, 'report_not_found'],
    [500, 'report_generation_failed'],
    [422, 'cycle_not_ready'],
  ] as const)('throws ApiError on %i %s', async (status, code) => {
    respond(status, envelope(code));
    await expect(reportPoll(CYCLE)).rejects.toBeInstanceOf(ApiError);
  });
});

describe('reportFetch (probe on open)', () => {
  it('returns null when no report exists', async () => {
    respond(404, envelope('report_not_found'));
    await expect(reportFetch(CYCLE)).resolves.toBeNull();
  });

  it('throws on 409 so the modal can switch to polling', async () => {
    respond(409, envelope('report_generation_in_progress'));
    await expect(reportFetch(CYCLE)).rejects.toBeInstanceOf(ApiError);
  });
});

describe('advisoryFetch', () => {
  it.each([
    [404, 'advisory_not_found'],
    [409, 'advisory_generation_in_progress'],
  ] as const)('treats %i %s as pending', async (status, code) => {
    respond(status, envelope(code));
    await expect(advisoryFetch(CYCLE)).resolves.toBeNull();
  });

  it('throws on a recorded failure', async () => {
    respond(500, envelope('advisory_generation_failed'));
    await expect(advisoryFetch(CYCLE)).rejects.toBeInstanceOf(ApiError);
  });
});
