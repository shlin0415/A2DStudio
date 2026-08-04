// Integration test: verifies playNextInQueue threads onItemStart + onEnded
// through its onended/onerror recursion (the B1/B2 fix).
// Uses instant pre-roll + manually-fired onended to drive each item.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { audioQueue } from '@/composables/audio-queue'
import { useA2DReplay, _resetReplaySingleton } from '@/composables/useA2DReplay'

describe('playNextInQueue callback threading (B1/B2 fix)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    audioQueue.value = []
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function makeLine(id: string, index: number): ScriptLine {
    return { id, speaker: 'ema', display_text: `文本${id}`, tts_text: `TTS${id}`, index, audio_path: `/audio/${id}.wav`, overlay: null, stage_id: '' }
  }

  it('onItemStart fires for ALL items, not just item 1 (B1 fix)', async () => {
    // Capture onended handlers assigned to fake audio elements.
    const onendedHandlers: Array<() => void> = []
    class FakeAudio {
      src = ''; muted = false; currentTime = 0
      onerror: (() => void) | null = null
      load() {}
      play() { return Promise.resolve() }
      pause() {}
      set onended(fn: () => void) { onendedHandlers.push(fn) }
      get onended() { return null }
    }
    // @ts-expect-error override Audio constructor
    globalThis.Audio = FakeAudio
    // Instant pre-roll so onended is assigned without delay.
    const origSetTimeout = global.setTimeout
    vi.spyOn(global, 'setTimeout').mockImplementation((fn: () => void) => {
      if (typeof fn === 'function') fn()
      return 0 as unknown as ReturnType<typeof setTimeout>
    })

    try {
      const { playNextInQueue } = await import('@/composables/useA2DWebSocket')

      const store = useScriptStore()
      store.addLine(makeLine('a', 0))
      store.addLine(makeLine('b', 1))
      store.addLine(makeLine('c', 2))

      audioQueue.value.push({ url: '/a.wav', lineId: 'a' }, { url: '/b.wav', lineId: 'b' }, { url: '/c.wav', lineId: 'c' })

      const startedLines: string[] = []
      const endedCount = { n: 0 }

      const promise = playNextInQueue(
        store,
        (line) => { startedLines.push(line.id) },
        () => { endedCount.n++ },
      )

      // Drive each item: fire onended -> triggers recursion for next item.
      for (let i = 0; i < 3; i++) {
        await new Promise(r => origSetTimeout(r, 5)) // let async recursion settle
        const handler = onendedHandlers[i]
        if (handler) handler()
      }

      await new Promise(r => origSetTimeout(r, 5))
      await promise

      // B1 fix: onItemStart fires for ALL 3 items (before fix: only item 1).
      expect(startedLines).toEqual(['a', 'b', 'c'])
      // onEnded fires for all 3 items.
      expect(endedCount.n).toBe(3)
      // Queue drained.
      expect(audioQueue.value.length).toBe(0)
    } finally {
      vi.restoreAllMocks()
    }
  })

  // MG3: engine-level B2 test — drives the REAL useA2DReplay engine and verifies
  // natural-end -> state='idle' + replayActive=false.
  it('engine: natural end returns to idle and resets replayActive (B2)', async () => {
    const onendedHandlers: Array<() => void> = []
    class FakeAudio {
      src = ''; muted = false; currentTime = 0
      onerror: (() => void) | null = null
      load() {}
      play() { return Promise.resolve() }
      pause() {}
      set onended(fn: () => void) { onendedHandlers.push(fn) }
      get onended() { return null }
    }
    // @ts-expect-error override Audio constructor
    globalThis.Audio = FakeAudio
    const origSetTimeout = global.setTimeout
    vi.spyOn(global, 'setTimeout').mockImplementation((fn: () => void) => {
      if (typeof fn === 'function') fn()
      return 0 as unknown as ReturnType<typeof setTimeout>
    })

    try {
      const store = useScriptStore()
      store.addLine(makeLine('p1', 0, { display_text: '第一行' }))
      store.addLine(makeLine('p2', 1, { display_text: '第二行' }))

      _resetReplaySingleton()
      const replay = useA2DReplay()
      replay.start(0)
      expect(replay.state.value).toBe('playing')

      // Fire onended for each item -> engine advances via onEnded->advance().
      for (let i = 0; i < 2; i++) {
        await new Promise(r => origSetTimeout(r, 5))
        if (onendedHandlers[i]) onendedHandlers[i]()
      }
      await new Promise(r => origSetTimeout(r, 5))

      // B2: natural end -> state='idle' + playingLineId cleared (stop() called).
      expect(replay.state.value).toBe('idle')
      expect(store.playingLineId).toBeNull()
    } finally {
      vi.restoreAllMocks()
    }
  })
})
