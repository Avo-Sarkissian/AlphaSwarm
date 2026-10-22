// Reports and the advisory render model-written links. On an http:// page browsers
// resolve link hostnames before any click unless the document turns DNS prefetching
// off, and that lookup alone would reach a host the model chose.
import { describe, expect, it } from 'vitest';
import indexHtml from '../../index.html?raw';

describe('index.html', () => {
  it('turns DNS prefetching off', () => {
    expect(indexHtml).toMatch(/<meta\s+http-equiv="x-dns-prefetch-control"\s+content="off"\s*\/?>/i);
  });
});
