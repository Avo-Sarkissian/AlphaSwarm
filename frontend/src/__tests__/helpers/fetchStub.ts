// Route-table fetch stub and small DOM shims for frontend tests.
import { vi } from 'vitest';

export interface StubRoute {
  /** HTTP method, default GET. */
  method?: string;
  /** Exact path, or the same path followed by "?query"; or a RegExp over the URL. */
  path: string | RegExp;
  /** Default 200. */
  status?: number;
  body: unknown;
}

export function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
    text: async () => JSON.stringify(body),
  } as unknown as Response;
}

function urlOf(input: RequestInfo | URL): string {
  if (typeof input === 'string') return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

/** Unmatched requests get a 404 error envelope, like an unknown backend route. */
export function stubFetch(routes: StubRoute[]) {
  const mock = vi.fn(async (input: RequestInfo | URL, init?: RequestInit): Promise<Response> => {
    const url = urlOf(input);
    const method = (init?.method ?? 'GET').toUpperCase();
    const hit = routes.find((r) => {
      if ((r.method ?? 'GET').toUpperCase() !== method) return false;
      return typeof r.path === 'string' ? url === r.path || url.startsWith(`${r.path}?`) : r.path.test(url);
    });
    if (!hit) {
      return jsonResponse({ detail: { error: 'not_found', message: `no stub for ${method} ${url}` } }, 404);
    }
    return jsonResponse(hit.body, hit.status ?? 200);
  });
  vi.stubGlobal('fetch', mock);
  return mock;
}

export function requestedUrls(mock: ReturnType<typeof stubFetch>): string[] {
  return mock.mock.calls.map(([input]) => urlOf(input));
}

/** The SVG graph observes its container; happy-dom may not ship ResizeObserver. */
export function ensureResizeObserver(): void {
  if (typeof globalThis.ResizeObserver === 'undefined') {
    vi.stubGlobal(
      'ResizeObserver',
      class {
        observe(): void {}
        unobserve(): void {}
        disconnect(): void {}
      },
    );
  }
}
