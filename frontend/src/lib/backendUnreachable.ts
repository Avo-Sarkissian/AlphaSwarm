// A request that never reached the backend. In production fetch rejects with a
// TypeError; behind the Vite dev proxy (vite.config.ts) a stopped backend would
// otherwise come back as HTTP 500 with an empty body, so the proxy answers
// with this error envelope instead and the UI shows the same hint either way.
// No imports: vite.config.ts loads this module in Node.

export const BACKEND_UNREACHABLE_CODE = 'backend_unreachable';
export const BACKEND_UNREACHABLE_MESSAGE = 'Cannot reach the backend. Is it running on port 8000?';

/** The part of Node's ServerResponse the proxy error handler writes to. */
interface HttpResponseLike {
  headersSent: boolean;
  writableEnded?: boolean;
  writeHead(status: number, headers: Record<string, string>): unknown;
  end(body?: string): unknown;
}

function isHttpResponse(res: unknown): res is HttpResponseLike {
  return typeof res === 'object' && res !== null && 'writeHead' in res && 'end' in res;
}

/**
 * http-proxy `error` listener for the dev server's /api proxy: answer 502 with
 * the backend_unreachable envelope. Registered before Vite's own handler, which
 * then sees the headers sent and writes nothing. A WebSocket upgrade passes a
 * socket, not a response, and is left to Vite.
 */
export function answerBackendUnreachable(_err: Error, _req: unknown, res: unknown): void {
  if (!isHttpResponse(res) || res.headersSent || res.writableEnded) return;
  res.writeHead(502, { 'content-type': 'application/json' });
  res.end(
    JSON.stringify({
      detail: { error: BACKEND_UNREACHABLE_CODE, message: BACKEND_UNREACHABLE_MESSAGE },
    }),
  );
}
