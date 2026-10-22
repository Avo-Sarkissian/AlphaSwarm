// Seed bounds mirrored from the backend's SeedText (alphaswarm.web.params):
// stripped length 10..2000. The UI caps input and disables Run, so a user
// never meets a 422 for a seed the browser could have checked.
export const SEED_MIN_LENGTH = 10;
export const SEED_MAX_LENGTH = 2000;

/** Why this seed cannot be run yet, or null when it is fine. */
export function seedProblem(seed: string): string | null {
  const length = seed.trim().length;
  if (length === 0) return 'Enter a seed rumor first.';
  if (length < SEED_MIN_LENGTH) return `The seed needs at least ${SEED_MIN_LENGTH} characters.`;
  if (length > SEED_MAX_LENGTH) return `The seed can have at most ${SEED_MAX_LENGTH} characters.`;
  return null;
}
