// Unmount everything React Testing Library rendered after each test (vitest runs
// without globals, so RTL cannot register this cleanup by itself).
import { cleanup } from '@testing-library/react';
import { afterEach } from 'vitest';

afterEach(() => {
  cleanup();
});
