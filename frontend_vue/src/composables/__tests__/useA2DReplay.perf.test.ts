import { describe, it, expect, beforeEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { useA2DReplay, _resetReplaySingleton } from '@/composables/useA2DReplay'
import { audioQueue } from '@/composables/audio-queue'

// Mock useA2DWebSocket so playNextInQueue doesn't touch real audio.
vi.mock('@/composables/useA2DWebSocket', () => ({
  playNextInQueue: vi.fn(),
  setReplayActive: vi.fn(),
  pauseCurrentAudio: vi.fn(),
  stopCurrentAudio: vi.fn(),
  mainAudioPlay: vi.fn(),
}))

// AC-9 performance: 1000-line replay cold-start + memory boundedness.
describe('AC-9 replay performance', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    audioQueue.value = []
    _resetReplaySingleton()
  })

  function makeLines(n: number): ScriptLine[] {
    return Array.from({ length: n }, (_, i) => ({
      id: `l${i}`, speaker: 'ema', display_text: `文本${i}`, tts_text: `TTS${i}`, index: i,
      audio_path: `/audio/l${i}.wav`, overlay: null, stage_id: '',
    }))
  }

  it('1000-line cold-start dispatches first audio_start within 500ms', () => {
    const store = useScriptStore()
    const lines = makeLines(1000)
    lines.forEach(l => store.addLine(l))

    const replay = useA2DReplay()

    // Time the cold-start path: start() -> enqueueFromIndex -> playNextInQueue.
    const t0 = performance.now()
    replay.start(0)
    const elapsed = performance.now() - t0

    // Cold-start (synchronous enqueue + first playNextInQueue call) < 500ms.
    expect(elapsed).toBeLessThan(500)
    expect(store.playingLineId).toBe('l0')
  })

  it('1000-line replay enqueues exactly all lines (bounded, not exponential)', () => {
    const store = useScriptStore()
    const lines = makeLines(1000)
    lines.forEach(l => store.addLine(l))

    const replay = useA2DReplay()
    replay.start(0)

    // Queue holds all 1000 lines (playNextInQueue mock consumes none).
    expect(audioQueue.value.length).toBe(1000)
  })
})
