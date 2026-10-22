import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { errorMessage, formatApiError, parseErrorEnvelope } from '../../lib/apiError';

describe('parseErrorEnvelope', () => {
  it('reads code and message from the envelope', () => {
    expect(
      parseErrorEnvelope({ detail: { error: 'cycle_not_found', message: 'No cycle x' } }),
    ).toEqual({ code: 'cycle_not_found', message: 'No cycle x' });
  });

  it('keeps a plain string detail as the message', () => {
    expect(parseErrorEnvelope({ detail: 'Not Found' })).toEqual({ code: null, message: 'Not Found' });
  });

  it.each([null, undefined, 'text', 42, {}, { detail: [] }, { detail: null }])(
    'returns nulls for %j',
    (body) => {
      expect(parseErrorEnvelope(body)).toEqual({ code: null, message: null });
    },
  );

  it('ignores non-string fields', () => {
    expect(parseErrorEnvelope({ detail: { error: 7, message: ['x'] } })).toEqual({
      code: null,
      message: null,
    });
  });
});

describe('errorMessage', () => {
  it("shows a refused run's envelope message", () => {
    const refused = new ApiError(
      409,
      {
        detail: {
          error: 'post_run_jobs_in_progress',
          message: 'The advisory/report jobs are using the orchestrator; retry when they finish',
        },
      },
      '/api/simulate/start',
    );
    expect(errorMessage(refused)).toBe(
      'The advisory/report jobs are using the orchestrator; retry when they finish',
    );
  });

  it('falls back to the HTTP status when the body has no message', () => {
    expect(errorMessage(new ApiError(502, 'Bad Gateway', '/api/simulate/start'))).toBe('HTTP 502');
  });

  it('uses the message of other errors', () => {
    expect(errorMessage(new TypeError('Failed to fetch'))).toBe('Failed to fetch');
    expect(errorMessage('offline')).toBe('offline');
  });
});

describe('formatApiError', () => {
  it('prefers the envelope message', () => {
    const err = new ApiError(
      409,
      { detail: { error: 'post_run_jobs_in_progress', message: 'The advisory/report jobs are using the orchestrator; retry when they finish' } },
      '/api/simulate/start',
    );
    expect(formatApiError(err)).toBe(
      'The advisory/report jobs are using the orchestrator; retry when they finish',
    );
  });

  it('falls back to the code and status', () => {
    const err = new ApiError(503, { detail: { error: 'graph_unavailable' } }, '/api/replay/cycles');
    expect(formatApiError(err)).toBe('graph unavailable (HTTP 503)');
  });

  it('reads FastAPI string details', () => {
    expect(formatApiError(new ApiError(404, { detail: 'Not Found' }, '/x'))).toBe('Not Found');
  });

  it('names the status when the body is not an envelope', () => {
    expect(formatApiError(new ApiError(502, '<html>bad gateway</html>', '/x'))).toBe(
      'Request failed (HTTP 502)',
    );
  });

  it('turns a network failure into a reachability hint', () => {
    expect(formatApiError(new TypeError('Failed to fetch'))).toBe(
      'Cannot reach the backend. Is it running on port 8000?',
    );
  });

  it('uses a plain error message and never returns an empty string', () => {
    expect(formatApiError(new Error('boom'))).toBe('boom');
    expect(formatApiError(undefined)).toBe('Something went wrong.');
  });
});
