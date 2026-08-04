import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import { useA2DReplay, _resetReplaySingleton } from '@/composables/useA2DReplay'
import { audioQueue } from '@/composables/audio-queue'
import { getCurrentBGM } from '@/composables/useA2DBGM'

// Mock useA2DWebSocket so playNextInQueue doesn't touch real audio.
vi.mock('@/composables/useA2DWebSocket', () => ({
  playNextInQueue: vi.fn(),
  setReplayActive: vi.fn(),
  pauseCurrentAudio: vi.fn(),
  stopCurrentAudio: vi.fn(),
  mainAudioPlay: vi.fn(),
}))

beforeEach(() => {
  setActivePinia(createPinia())
  audioQueue.value = []
  _resetReplaySingleton()
})

function makeLine(id: string, index: number, extra: Partial<ScriptLine> = {}): ScriptLine {
  return {
    id, speaker: 'ema', display_text: `文本${id}`, tts_text: `TTS${id}`, index,
    audio_path: `/audio/${id}.wav`, overlay: null, stage_id: '', ...extra,
  }
}

describe('useA2DReplay state machine', () => {
  it('starts idle', () => {
    const replay = useA2DReplay()
    expect(replay.state.value).toBe('idle')
  })

  it('transitions idle → loading → playing on start()', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    store.addLine(makeLine('b', 1))

    const replay = useA2DReplay()
    replay.start(0)
    expect(replay.state.value).toBe('playing')
    expect(store.playingLineId).toBe('a')
  })

  it('start from arbitrary index (AC-2 partial)', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    store.addLine(makeLine('b', 1))
    store.addLine(makeLine('c', 2))

    const replay = useA2DReplay()
    replay.start(1)
    expect(store.playingLineId).toBe('b')
    expect(replay.currentIndex.value).toBe(1)
  })

  it('does not crash on empty script', () => {
    const replay = useA2DReplay()
    replay.start(0)
    expect(replay.state.value).toBe('idle')
    expect(replay.error.value).toBe('无内容可重播')
  })

  it('enqueues audio for sequential playback', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    store.addLine(makeLine('b', 1))

    const replay = useA2DReplay()
    replay.start(0)
    expect(audioQueue.value.length).toBe(2)
    expect(audioQueue.value[0].lineId).toBe('a')
    expect(audioQueue.value[1].lineId).toBe('b')
  })

  it('skips lines without audio_path', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    store.addLine(makeLine('b', 1, { audio_path: null }))

    const replay = useA2DReplay()
    replay.start(0)
    expect(audioQueue.value.length).toBe(1)
    expect(audioQueue.value[0].lineId).toBe('a')
  })

  it('pause ↔ resume transitions', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    const replay = useA2DReplay()
    replay.start(0)
    replay.pause()
    expect(replay.state.value).toBe('paused')
    expect(replay.isPaused.value).toBe(true)
    replay.resume()
    expect(replay.state.value).toBe('playing')
  })

  it('stop resets to idle', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    const replay = useA2DReplay()
    replay.start(0)
    replay.stop()
    expect(replay.state.value).toBe('idle')
    expect(store.playingLineId).toBeNull()
  })

  it('advance moves to next line', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    store.addLine(makeLine('b', 1))
    const replay = useA2DReplay()
    replay.start(0)
    const continued = replay.advance()
    expect(continued).toBe(true)
    expect(store.playingLineId).toBe('b')
  })

  it('advance returns false at end and stops', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    const replay = useA2DReplay()
    replay.start(0)
    const continued = replay.advance()
    expect(continued).toBe(false)
    expect(replay.state.value).toBe('idle')
  })

  it('seek to target index', () => {
    const store = useScriptStore()
    store.addLine(makeLine('a', 0))
    store.addLine(makeLine('b', 1))
    store.addLine(makeLine('c', 2))
    const replay = useA2DReplay()
    replay.start(0)
    replay.seek(2)
    expect(store.playingLineId).toBe('c')
    expect(replay.currentIndex.value).toBe(2)
  })

  // AC-7: all lines missing audio -> idle + error (finite guard).
  it('AC-7 negative: all-missing-audio returns idle with error', () => {
    const store = useScriptStore()
    store.addLine(makeLine('m1', 0, { audio_path: null }))
    store.addLine(makeLine('m2', 1, { audio_path: null }))
    const replay = useA2DReplay()
    replay.start(0)
    expect(replay.state.value).toBe('idle')
    expect(replay.error.value).toBe('所有行均缺失音频')
  })

  // AC-7: missing line doesn't block subsequent normal line.
  it('AC-7 positive: missing audio line skipped, normal line plays', () => {
    const store = useScriptStore()
    store.addLine(makeLine('x1', 0, { audio_path: null })) // missing
    store.addLine(makeLine('x2', 1)) // has audio
    const replay = useA2DReplay()
    replay.start(0)
    expect(replay.state.value).toBe('playing')
    // Queue should contain only x2 (x1 skipped).
    expect(audioQueue.value.length).toBe(1)
    expect(audioQueue.value[0].lineId).toBe('x2')
  })

  // AC-7: skippedLines counter tracks skipped lines.
  it('AC-7: skippedLines counter increments for missing audio', () => {
    const store = useScriptStore()
    store.addLine(makeLine('s1', 0, { audio_path: null }))
    store.addLine(makeLine('s2', 1, { audio_path: null }))
    store.addLine(makeLine('s3', 2)) // has audio
    const replay = useA2DReplay()
    replay.start(0)
    expect(replay.skippedLines.value).toEqual(['s1', 's2'])
  })
})

