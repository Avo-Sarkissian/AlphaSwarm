// Static demo data source: replays one committed cycle export in the browser
// (docs/DECISIONS.md#adr-cycle-export). demo/index.json names the cycle; its
// export becomes one replay frame per round. The UI's replay seeks move the
// player; every other API call is answered by demoRoutes or refused.
import { ApiError, type RequestOptions } from '../api/client';
import { requestCascadeAutoplay } from '../lib/cascadeIntent';
import { parseCycleExport, type CycleExport } from './cycleExport';
import { answerDemoRequest } from './demoRoutes';
import { exportToFrames } from './exportFrames';
import type { ConnectionStatus, DataSource } from './types';

export const DEMO_INDEX_FILE = 'demo/index.json';
// No '/', '.' or '%': the id names one file inside demo/. Real ids are uuid4;
// '<', '>' and ':' admit the golden fixture's normalized id "<UUID:1>" in tests.
const SAFE_ID = /^[A-Za-z0-9_:<>-]+$/;

export interface DemoOptions {
  /** Defaults to import.meta.env.BASE_URL (vite `base`). */
  baseUrl?: string;
  loadJson?: (url: string) => Promise<unknown>;
}

interface LoadedCycle {
  exp: CycleExport;
  frames: unknown[];
}

async function fetchJsonFile(url: string): Promise<unknown> {
  const res = await fetch(url);
  if (!res.ok) throw new Error(`demo file ${url}: HTTP ${res.status}`);
  return res.json();
}

export function createDemoDataSource(opts: DemoOptions = {}): DataSource {
  const base = opts.baseUrl ?? import.meta.env.BASE_URL;
  const loadJson = opts.loadJson ?? fetchJsonFile;
  const listeners = new Set<(raw: unknown) => void>();
  let loading: Promise<LoadedCycle> | null = null;
  let round = 1;
  let autoplayRequested = false;

  function load(): Promise<LoadedCycle> {
    loading ??= (async () => {
      const index = (await loadJson(`${base}${DEMO_INDEX_FILE}`)) as { cycle_id?: unknown } | null;
      const id = index?.cycle_id;
      if (typeof id !== 'string' || !SAFE_ID.test(id)) throw new Error('demo index names no valid cycle');
      const exp = parseCycleExport(await loadJson(`${base}demo/${encodeURIComponent(id)}.json`));
      return { exp, frames: exportToFrames(exp) };
    })().catch((e: unknown) => {
      loading = null; // the next subscription retries
      throw e;
    });
    return loading;
  }

  return {
    kind: 'demo',
    readOnly: true,
    subscribeFrames(onFrame: (raw: unknown) => void, onStatus: (s: ConnectionStatus) => void) {
      let active = true;
      listeners.add(onFrame);
      onStatus('connecting');
      load().then(
        (cycle) => {
          if (!active) return;
          if (!autoplayRequested) {
            autoplayRequested = true;
            requestCascadeAutoplay(cycle.exp.cycle.cycle_id);
          }
          onStatus('open');
          const frame = cycle.frames[round - 1];
          if (frame !== undefined) onFrame(frame);
        },
        () => {
          if (active) onStatus('closed');
        },
      );
      return () => {
        active = false;
        listeners.delete(onFrame);
      };
    },
    async fetchJson<T>(path: string, init?: RequestOptions): Promise<T> {
      const cycle = await load();
      const answer = answerDemoRequest(cycle.exp, init?.method ?? 'GET', path, round);
      if (answer.kind === 'error') {
        throw new ApiError(answer.status, { detail: { error: answer.code, message: answer.message } }, path, answer.message, answer.code);
      }
      if (answer.kind === 'seek') {
        round = answer.round;
        const frame = cycle.frames[round - 1];
        if (frame !== undefined) for (const listener of listeners) listener(frame);
      }
      return answer.body as T;
    },
  };
}
