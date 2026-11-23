import type { ServerEvent } from "./types";

export type ConnectionState = "connecting" | "open" | "closed";

interface Options {
  onEvent: (event: ServerEvent) => void;
  onStateChange: (state: ConnectionState) => void;
}

/** WebSocket that reconnects with backoff and queues messages sent while offline. */
export class ChatSocket {
  private ws: WebSocket | null = null;
  private queue: string[] = [];
  private retries = 0;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private closedByUser = false;

  constructor(private url: string, private opts: Options) {}

  connect(): void {
    this.closedByUser = false;
    this.opts.onStateChange("connecting");
    const ws = new WebSocket(this.url);
    this.ws = ws;

    ws.onopen = () => {
      this.retries = 0;
      this.opts.onStateChange("open");
      while (this.queue.length && ws.readyState === WebSocket.OPEN) ws.send(this.queue.shift()!);
    };
    ws.onmessage = (msg) => {
      try {
        this.opts.onEvent(JSON.parse(msg.data) as ServerEvent);
      } catch {
        // ignore malformed frames
      }
    };
    ws.onclose = () => {
      this.opts.onStateChange("closed");
      if (!this.closedByUser) this.scheduleReconnect();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleReconnect(): void {
    const delay = Math.min(1000 * 2 ** this.retries, 15000);
    this.retries += 1;
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  send(message: string): void {
    const payload = JSON.stringify({ message });
    if (this.ws?.readyState === WebSocket.OPEN) this.ws.send(payload);
    else this.queue.push(payload);
  }

  close(): void {
    this.closedByUser = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.ws?.close();
    this.ws = null;
  }
}
