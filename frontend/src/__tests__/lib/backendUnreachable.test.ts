// The Vite dev proxy's answer when the backend on :8000 is down, and how the
// UI reads it. Without the hook the proxy answers 500 with an empty body.
import type { ProxyOptions } from 'vite';
import { describe, expect, it, vi } from 'vitest';
import viteConfig from '../../../vite.config';
import { ApiError } from '../../api/client';
import { formatApiError, isBackendUnreachable } from '../../lib/apiError';
import { answerBackendUnreachable } from '../../lib/backendUnreachable';

const HINT = 'Cannot reach the backend. Is it running on port 8000?';

function fakeResponse(headersSent = false) {
  const res = {
    headersSent,
    writableEnded: false,
    status: 0,
    headers: {} as Record<string, string>,
    body: '',
    writeHead: vi.fn((status: number, headers: Record<string, string>) => {
      res.status = status;
      res.headers = headers;
      return res;
    }),
    end: vi.fn((body?: string) => {
      res.body = body ?? '';
      res.writableEnded = true;
      return res;
    }),
  };
  return res;
}

const refused = new Error('connect ECONNREFUSED 127.0.0.1:8000');

describe('answerBackendUnreachable', () => {
  it('answers a failed /api request with a JSON 502 envelope', () => {
    const res = fakeResponse();
    answerBackendUnreachable(refused, {}, res);
    expect(res.status).toBe(502);
    expect(res.headers['content-type']).toBe('application/json');
    expect(JSON.parse(res.body)).toEqual({
      detail: { error: 'backend_unreachable', message: HINT },
    });
  });

  it('is read by the UI as the reachability hint', () => {
    const res = fakeResponse();
    answerBackendUnreachable(refused, {}, res);
    const err = new ApiError(502, JSON.parse(res.body), '/api/simulate/start');
    expect(isBackendUnreachable(err)).toBe(true);
    expect(formatApiError(err)).toBe(HINT);
  });

  it('leaves a response alone once its headers are sent', () => {
    const res = fakeResponse(true);
    answerBackendUnreachable(refused, {}, res);
    expect(res.writeHead).not.toHaveBeenCalled();
    expect(res.end).not.toHaveBeenCalled();
  });

  it('ignores a WebSocket upgrade socket', () => {
    const socket = { end: vi.fn() };
    answerBackendUnreachable(refused, {}, socket);
    expect(socket.end).not.toHaveBeenCalled();
  });
});

describe('vite.config.ts', () => {
  it("registers the handler on the /api proxy's error event", () => {
    const api = viteConfig.server?.proxy?.['/api'] as ProxyOptions;
    const on = vi.fn();
    api.configure?.({ on } as unknown as Parameters<NonNullable<ProxyOptions['configure']>>[0], api);
    expect(on).toHaveBeenCalledWith('error', answerBackendUnreachable);
  });
});
