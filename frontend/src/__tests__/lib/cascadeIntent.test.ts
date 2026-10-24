import { describe, expect, it } from 'vitest';
import { requestCascadeAutoplay, takeCascadeAutoplay } from '../../lib/cascadeIntent';

describe('cascade autoplay request', () => {
  it('is taken once, by the same cycle only', () => {
    requestCascadeAutoplay('cyc-a');
    expect(takeCascadeAutoplay('cyc-b')).toBe(false);
    expect(takeCascadeAutoplay(null)).toBe(false);
    expect(takeCascadeAutoplay('cyc-a')).toBe(true);
    expect(takeCascadeAutoplay('cyc-a')).toBe(false);
  });
});
