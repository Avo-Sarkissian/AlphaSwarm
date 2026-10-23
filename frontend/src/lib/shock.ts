// Shock limits mirror ShockText in alphaswarm.web.params (10..1000 chars after trim).
export const SHOCK_MIN_CHARS = 10;
export const SHOCK_MAX_CHARS = 1000;

/**
 * First round a shock queued now would reach, or null when the window is closed.
 * Rounds 2..numRounds are gated, so a shock queued during seeding or round 1
 * lands before round 2 and stays active for every later round.
 */
export function shockTargetRound(roundNum: number | null, numRounds: number, windowOpen: boolean): number | null {
  if (!windowOpen) return null;
  const next = Math.max(2, (roundNum ?? 0) + 1);
  return next <= numRounds ? next : null;
}

export function shockLengthError(text: string): string | null {
  const n = text.trim().length;
  if (n === 0) return null;
  if (n < SHOCK_MIN_CHARS) return `At least ${SHOCK_MIN_CHARS} characters (${n} so far)`;
  if (n > SHOCK_MAX_CHARS) return `At most ${SHOCK_MAX_CHARS} characters`;
  return null;
}
