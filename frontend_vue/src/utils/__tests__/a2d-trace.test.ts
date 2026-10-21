import { afterEach, describe, expect, it, vi } from 'vitest'
import { dumpTrace, emitTrace, sanitizeTraceEntry } from '../a2d-trace'

describe('A2D timing trace privacy', () => {
  afterEach(() => {
    dumpTrace()
    vi.restoreAllMocks()
  })

  it('keeps only allow-listed metadata in exported diagnostics', () => {
    const safe = sanitizeTraceEntry({
      ts: 12.5,
      wall: 1700000000000,
      event: 'ws_script_line',
      data: {
        lineId: 'line-1',
        tts_text: 'private dialogue',
        audio_url: 'http://127.0.0.1:8765/audio/private.wav',
        api_key: 'must-never-export',
      },
    })

    expect(safe).toEqual({
      ts: 12.5,
      wall: 1700000000000,
      event: 'ws_script_line',
      data: { lineId: 'line-1' },
    })
    expect(JSON.stringify(safe)).not.toContain('private dialogue')
    expect(JSON.stringify(safe)).not.toContain('private.wav')
    expect(JSON.stringify(safe)).not.toContain('must-never-export')
  })

  it('prints a sanitized console entry while retaining the raw page trace for ASR evaluation', () => {
    const consoleInfo = vi.spyOn(console, 'info').mockImplementation(() => {})

    emitTrace('ws_script_line', { lineId: 'line-2', tts_text: 'private dialogue' })

    const trace = window.__a2dTrace
    expect(trace.at(-1)?.data?.tts_text).toBe('private dialogue')
    expect(JSON.stringify(consoleInfo.mock.calls)).not.toContain('private dialogue')
    expect(JSON.stringify(consoleInfo.mock.calls)).toContain('line-2')
  })

  it('exports line completion with its identifier and no content or resource paths', () => {
    const safe = sanitizeTraceEntry({
      ts: 5,
      wall: 1700000000000,
      event: 'line_complete',
      data: {
        lineId: 'line-3',
        tts_text: 'private dialogue',
        audio_url: 'http://127.0.0.1:8765/audio/private.wav',
      },
    })

    expect(safe.data).toEqual({ lineId: 'line-3' })
    expect(JSON.stringify(safe)).not.toContain('private dialogue')
    expect(JSON.stringify(safe)).not.toContain('private.wav')
  })
})
