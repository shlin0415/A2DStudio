/** Structured event timeline for debugging A2D UI/audio sync bugs.

 *  Usage: import { emitTrace } from '@/utils/a2d-trace'
 *         emitTrace('audio_start', { lineId, batchIndex: '2/3' })
 *
 *  Dual output:
 *    1. window.__a2dTrace ring buffer (pulled by Playwright page.evaluate)
 *    2. console.info('[A2D-Trace]', ...) for live browser console + monitor capture
 */

const MAX = 500

export interface TraceEntry {
  ts: number   // performance.now() — sub-ms precision since page load
  wall: number // Date.now() — absolute epoch ms, aligns with backend logs
  event: string
  data?: Record<string, unknown>
}

declare global {
  interface Window {
    __a2dTrace: TraceEntry[]
  }
}

// Survives HMR (Vite dev server) — don't overwrite on module re-eval
window.__a2dTrace = window.__a2dTrace || []

/** Emit a single trace event. */
export function emitTrace(event: string, data?: Record<string, unknown>): void {
  const entry: TraceEntry = {
    ts: Math.round(performance.now() * 100) / 100,
    wall: Date.now(),
    event,
    data,
  }
  const arr = window.__a2dTrace
  if (arr.length >= MAX) {
    arr.splice(0, arr.length - MAX + 1)
  }
  arr.push(entry)
  console.info('[A2D-Trace]', JSON.stringify(entry))
}

/** Dump current trace buffer (clears it). Returns a copy. */
export function dumpTrace(): TraceEntry[] {
  const copy = [...window.__a2dTrace]
  window.__a2dTrace.length = 0
  return copy
}
