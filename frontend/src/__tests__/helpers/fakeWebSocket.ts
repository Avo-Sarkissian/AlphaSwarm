// Minimal stand-in for window.WebSocket. Tests drive the lifecycle by hand with
// open(), message(data) and drop(); every constructed socket is recorded.
export class FakeWebSocket {
  static instances: FakeWebSocket[] = [];
  static throwOnConstruct = false;

  static reset(): void {
    FakeWebSocket.instances = [];
    FakeWebSocket.throwOnConstruct = false;
  }

  static latest(): FakeWebSocket {
    const ws = FakeWebSocket.instances.at(-1);
    if (!ws) throw new Error('no FakeWebSocket constructed yet');
    return ws;
  }

  readonly url: string;
  onopen: ((ev: Event) => void) | null = null;
  onmessage: ((ev: MessageEvent) => void) | null = null;
  onerror: ((ev: Event) => void) | null = null;
  onclose: ((ev: CloseEvent) => void) | null = null;
  closeCalls = 0;

  constructor(url: string) {
    if (FakeWebSocket.throwOnConstruct) throw new Error('construct failed');
    this.url = url;
    FakeWebSocket.instances.push(this);
  }

  open(): void {
    this.onopen?.(new Event('open'));
  }

  message(data: string): void {
    this.onmessage?.(new MessageEvent('message', { data }));
  }

  /** Server restart or network loss: fires onclose like a real socket. */
  drop(): void {
    this.onclose?.(new CloseEvent('close'));
  }

  close(): void {
    this.closeCalls += 1;
  }
}
