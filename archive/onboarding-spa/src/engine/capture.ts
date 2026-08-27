// ─── CaptureSink — event capture abstraction ────────────────────────────────
//
// The MVP ships InMemoryCaptureSink. A real backend just implements the same
// interface — the UI never changes.

export interface CaptureEvent {
  type: string
  payload: Record<string, unknown>
  ts: number
}

export interface CaptureSink {
  record(event: CaptureEvent): void
  all(): CaptureEvent[]
  exportJson(): string
}

// ─── In-memory implementation ────────────────────────────────────────────────

export class InMemoryCaptureSink implements CaptureSink {
  private events: CaptureEvent[] = []

  record(event: CaptureEvent) {
    this.events.push(event)
  }

  all(): CaptureEvent[] {
    return [...this.events]
  }

  exportJson(): string {
    return JSON.stringify(this.events, null, 2)
  }
}

// ─── Singleton for the session ───────────────────────────────────────────────

export const captureSink: CaptureSink = new InMemoryCaptureSink()

// ─── Helper: emit a typed event ──────────────────────────────────────────────

export function capture(
  type: string,
  payload: Record<string, unknown> = {},
) {
  captureSink.record({ type, payload, ts: Date.now() })
}
