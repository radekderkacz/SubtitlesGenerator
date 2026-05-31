import '@testing-library/jest-dom'

// jsdom doesn't implement ResizeObserver — TanStack Virtual + several base-ui
// primitives rely on it. Provide a no-op so tests don't crash.
class ResizeObserverStub {
  observe(): void {
    return
  }
  unobserve(): void {
    return
  }
  disconnect(): void {
    return
  }
}
;(globalThis as { ResizeObserver?: typeof ResizeObserver }).ResizeObserver =
  ResizeObserverStub as unknown as typeof ResizeObserver

// jsdom doesn't implement EventSource. Provide a no-op stub so any component
// that calls `new EventSource(...)` (e.g. via `useJobStream`) doesn't crash.
// Tests that need to control event delivery override `globalThis.EventSource`
// per-test (see useJobStream.test.tsx).
class EventSourceStub {
  url: string
  readyState = 0
  onopen: ((ev: Event) => void) | null = null
  onerror: ((ev: Event) => void) | null = null
  onmessage: ((ev: MessageEvent) => void) | null = null
  constructor(url: string) {
    this.url = url
  }
  addEventListener(): void {
    return
  }
  removeEventListener(): void {
    return
  }
  close(): void {
    return
  }
  dispatchEvent(): boolean {
    return true
  }
}
;(globalThis as { EventSource?: typeof EventSource }).EventSource =
  EventSourceStub as unknown as typeof EventSource
