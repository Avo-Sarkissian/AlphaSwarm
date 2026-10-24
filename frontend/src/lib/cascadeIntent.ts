// A one-shot "play the cascade when this cycle's replay appears" request. Set
// by whoever starts a replay (the finished-run button, the static demo) and
// taken by the ReplayBar when it mounts for that cycle.
let pending: string | null = null;

export function requestCascadeAutoplay(cycleId: string): void {
  pending = cycleId;
}

export function takeCascadeAutoplay(cycleId: string | null): boolean {
  if (cycleId === null || pending !== cycleId) return false;
  pending = null;
  return true;
}
