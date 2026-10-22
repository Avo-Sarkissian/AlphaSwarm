import { describe, expect, it } from 'vitest';
import { parseErrorEnvelope } from '../../lib/apiError';

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
