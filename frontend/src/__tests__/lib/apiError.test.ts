import { describe, expect, it } from 'vitest';
import { ApiError } from '../../api/client';
import { errorMessage, parseErrorEnvelope } from '../../lib/apiError';

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
