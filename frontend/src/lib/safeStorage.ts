// localStorage that never throws: private windows, blocked site data and full
// quotas all degrade to "nothing stored" instead of crashing the render.
function storage(): Storage | null {
  try {
    return typeof window === 'undefined' ? null : window.localStorage;
  } catch {
    return null;
  }
}

export const safeStorage = {
  get(key: string): string | null {
    try {
      return storage()?.getItem(key) ?? null;
    } catch {
      return null;
    }
  },
  set(key: string, value: string): void {
    try {
      storage()?.setItem(key, value);
    } catch {
      // blocked, full or private mode: the value is a convenience only
    }
  },
};
