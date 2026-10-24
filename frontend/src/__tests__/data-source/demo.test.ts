// @vitest-environment happy-dom
import { describe, expect, it, vi } from 'vitest';
import { ApiError, DEMO_UNAVAILABLE_CODE } from '../../api/client';
import type { ConnectionStatus } from '../../data-source';
import { createDemoDataSource } from '../../data-source/demo';
import { takeCascadeAutoplay } from '../../lib/cascadeIntent';
import fixture from '../fixtures/cycle_export.json';

const ID = fixture.cycle.cycle_id;
const FILES: Record<string, unknown> = {
  '/base/demo/index.json': { cycle_id: ID },
  [`/base/demo/${encodeURIComponent(ID)}.json`]: fixture,
};

function source(files: Record<string, unknown> = FILES) {
  const loadJson = vi.fn(async (url: string) => {
    if (url in files) return files[url];
    throw new Error(`404 ${url}`);
  });
  return { demo: createDemoDataSource({ baseUrl: '/base/', loadJson }), loadJson };
}

function watch(demo: ReturnType<typeof createDemoDataSource>) {
  const frames: Array<{ round_num?: number }> = [];
  const statuses: ConnectionStatus[] = [];
  const stop = demo.subscribeFrames((raw) => frames.push(raw as { round_num?: number }), (s) => statuses.push(s));
  return { frames, statuses, stop };
}

describe('demo data source', () => {
  it('emits Round 1 once loaded and asks for the cascade once', async () => {
    const { demo, loadJson } = source();
    const first = watch(demo);
    await vi.waitFor(() => expect(first.frames).toHaveLength(1));
    expect(first.frames[0]?.round_num).toBe(1);
    expect(first.statuses).toEqual(['connecting', 'open']);
    expect(takeCascadeAutoplay(ID)).toBe(true);
    const second = watch(demo);
    await vi.waitFor(() => expect(second.frames).toHaveLength(1));
    expect(takeCascadeAutoplay(ID)).toBe(false);
    expect(loadJson).toHaveBeenCalledTimes(2);
    first.stop();
    second.stop();
  });

  it('pushes the new round to every subscriber after a seek', async () => {
    const { demo } = source();
    const a = watch(demo);
    const b = watch(demo);
    await vi.waitFor(() => expect(b.frames).toHaveLength(1));
    expect(await demo.fetchJson('/api/replay/round/3', { method: 'POST' })).toEqual({ status: 'ok', round_num: 3 });
    expect(a.frames.at(-1)?.round_num).toBe(3);
    expect(b.frames.at(-1)?.round_num).toBe(3);
    a.stop();
    b.stop();
  });

  it('answers reads and refuses what it cannot do', async () => {
    const { demo } = source();
    const citations = await demo.fetchJson<{ round_num: number }>(`/api/cycles/${encodeURIComponent(ID)}/citations?round=2`);
    expect(citations.round_num).toBe(2);
    await expect(demo.fetchJson('/api/holdings')).rejects.toBeInstanceOf(ApiError);
    await expect(demo.fetchJson('/api/holdings')).rejects.toMatchObject({ status: 503, code: DEMO_UNAVAILABLE_CODE });
  });

  it('reports closed when the recorded cycle cannot be loaded', async () => {
    const { demo } = source({ '/base/demo/index.json': { cycle_id: ID } });
    const view = watch(demo);
    await vi.waitFor(() => expect(view.statuses).toEqual(['connecting', 'closed']));
    expect(view.frames).toEqual([]);
  });

  it('rejects an index that points outside the demo folder', async () => {
    const { demo } = source({ '/base/demo/index.json': { cycle_id: '../secrets' } });
    const view = watch(demo);
    await vi.waitFor(() => expect(view.statuses).toEqual(['connecting', 'closed']));
  });

  it('stops sending to an unsubscribed listener', async () => {
    const { demo } = source();
    const view = watch(demo);
    await vi.waitFor(() => expect(view.frames).toHaveLength(1));
    view.stop();
    await demo.fetchJson('/api/replay/round/2', { method: 'POST' });
    expect(view.frames).toHaveLength(1);
  });
});
