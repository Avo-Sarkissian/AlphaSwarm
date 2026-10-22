// Test helper: route global fetch by "METHOD /path" (query string ignored).
// A handler may be a fixed reply or a function of the 1-based call count.
import { vi } from 'vitest';

export interface RouteReply {
  status?: number;
  body: unknown;
}

export type RouteHandler = RouteReply | ((call: number) => RouteReply);

export function stubFetchRoutes(routes: Record<string, RouteHandler>) {
  const calls = new Map<string, number>();
  const fetchMock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = typeof input === 'string' ? input : input instanceof URL ? input.toString() : input.url;
    const path = url.replace(/^https?:\/\/[^/]+/, '').split('?')[0];
    const key = `${(init?.method ?? 'GET').toUpperCase()} ${path}`;
    const call = (calls.get(key) ?? 0) + 1;
    calls.set(key, call);
    const handler = routes[key];
    const reply: RouteReply =
      handler === undefined
        ? { status: 404, body: { detail: { error: 'not_mocked', message: key } } }
        : typeof handler === 'function'
          ? handler(call)
          : handler;
    return new Response(JSON.stringify(reply.body), {
      status: reply.status ?? 200,
      headers: { 'content-type': 'application/json' },
    });
  });
  vi.stubGlobal('fetch', fetchMock);
  return fetchMock;
}
