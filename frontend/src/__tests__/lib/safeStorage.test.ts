// @vitest-environment happy-dom
import { afterEach, describe, expect, it, vi } from 'vitest';
import { safeStorage } from '../../lib/safeStorage';

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe('safeStorage', () => {
  it('reads back what it wrote', () => {
    safeStorage.set('as_test', 'v');
    expect(safeStorage.get('as_test')).toBe('v');
  });

  it('returns null when getItem throws', () => {
    vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => {
      throw new DOMException('denied', 'SecurityError');
    });
    expect(safeStorage.get('as_test')).toBeNull();
  });

  it('swallows a failing setItem', () => {
    vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => {
      throw new DOMException('full', 'QuotaExceededError');
    });
    expect(() => safeStorage.set('as_test', 'v')).not.toThrow();
  });

  it('survives a blocked localStorage getter', () => {
    const own = Object.getOwnPropertyDescriptor(window, 'localStorage');
    Object.defineProperty(window, 'localStorage', {
      configurable: true,
      get() {
        throw new DOMException('blocked', 'SecurityError');
      },
    });
    try {
      expect(safeStorage.get('as_test')).toBeNull();
      expect(() => safeStorage.set('as_test', 'v')).not.toThrow();
    } finally {
      if (own) Object.defineProperty(window, 'localStorage', own);
      else delete (window as unknown as Record<string, unknown>).localStorage;
    }
  });
});
