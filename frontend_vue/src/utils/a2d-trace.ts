/** Structured event timeline for debugging A2D UI/audio sync bugs.

 *  Usage: import { emitTrace } from '@/utils/a2d-trace'
 *         emitTrace('audio_start', { lineId, batchIndex: '2/3' })
 *
 *  Dual output:
 *    1. window.__a2dTrace ring buffer (pulled by Playwright page.evaluate)
 *    2. console.info('[A2D-Trace]', ...) for live browser console + monitor capture
 */

const MAX = 500
const DOWNLOAD_URL_REVOKE_DELAY_MS = 1000

const SAFE_TRACE_FIELDS: Record<string, readonly string[]> = {
  phase_change: ['from', 'to'],
  script_line: ['lineId', 'index', 'batch_index', 'batch_total'],
  currentLine: ['lineId', 'index'],
  review_preview: ['lineId', 'index', 'source'],
  review_preview_hide: ['lineId', 'index'],
  ws_script_line: ['lineId'],
  ws_script_line_ignored: ['lineId', 'reason'],
  ws_tts_ready: ['lineId'],
  audio_queued: ['lineId'],
  audio_deferred_replay_active: ['lineId'],
  audio_start: ['lineId'],
  playingLine: ['lineId'],
  preroll_start: ['lineId', 'firstPlay'],
  preroll_end: ['lineId', 'preRollMs'],
  audio_end: ['lineId'],
  audio_error: ['lineId'],
  audio_play_failed: ['lineId'],
  emotion: ['lineId'],
  subtitle_show: ['lineId', 'lineIndex', 'characterCount'],
  subtitle_hide: ['lineId'],
  stage_action_start: ['actionId', 'kind', 'lineId', 'roleId'],
  stage_action_end: ['actionId', 'kind', 'lineId', 'roleId', 'outcome'],
  stage_action_wait: ['lineId', 'pendingCount'],
}

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

/** Keep only the fields needed to diagnose ordering and timing. */
export function sanitizeTraceEntry(entry: TraceEntry): TraceEntry {
  const allowedFields = SAFE_TRACE_FIELDS[entry.event] ?? []
  const data: Record<string, unknown> = {}
  for (const field of allowedFields) {
    const value = entry.data?.[field]
    if (value !== undefined) data[field] = value
  }
  return {
    ts: entry.ts,
    wall: entry.wall,
    event: entry.event,
    ...(Object.keys(data).length === 0 ? {} : { data }),
  }
}

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
  // The page ring retains the full payload for the existing ASR evaluation hook;
  // the console receives only timing metadata to avoid printing dialogue or paths.
  console.info('[A2D-Trace]', JSON.stringify(sanitizeTraceEntry(entry)))
}

/** Dump current trace buffer (clears it). Returns a copy. */
export function dumpTrace(): TraceEntry[] {
  const copy = [...window.__a2dTrace]
  window.__a2dTrace.length = 0
  return copy
}

/** Download a metadata-only trace without clearing the in-page ASR trace buffer. */
export function downloadSafeTrace(): void {
  const trace = window.__a2dTrace.map(sanitizeTraceEntry)
  const blob = new Blob([JSON.stringify(trace, null, 2)], { type: 'application/json' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `a2d-timing-${new Date().toISOString().replace(/[:.]/g, '-')}.json`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  window.setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_URL_REVOKE_DELAY_MS)
}
