// Integration test: verifies playNextInQueue threads onItemStart + onEnded
// through its onended/onerror recursion (the B1/B2 fix).
// Uses instant pre-roll + manually-fired onended to drive each item.
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import { audioQueue, isAudioPlaying } from '@/composables/audio-queue'
import { useA2DReplay, _resetReplaySingleton } from '@/composables/useA2DReplay'
import { getCurrentBGM, playBGM, stopBGM } from '@/composables/useA2DBGM'

describe('playNextInQueue callback threading (B1/B2 fix)', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    audioQueue.value = []
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  function makeLine(id: string, index: number, extra: Partial<ScriptLine> = {}): ScriptLine {
    return { id, speaker: 'ema', display_text: `文本${id}`, tts_text: `TTS${id}`, index, audio_path: `/audio/${id}.wav`, overlay: null, stage_id: '', ...extra }
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
      // Seed a role with a non-idle emotion so the MG2 reset is verifiable.
      useGameStore().importFromSnapshot({
        gameRoles: { 1: { roleId: 1, roleName: 'ema', emotion: '开心', originalEmotion: '开心', scale: 1, offsetX: 0, offsetY: 0, show: true } },
        presentRoleIds: [1],
      })
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
      // AC-3 negative: subtitle cleared at replay end.
      expect(replay.currentSubtitle.value).toBe('')
      // AC-3 negative: emotion returns to idle for all roles (MG2 stop() reset).
      for (const role of Object.values(useGameStore().gameRoles)) {
        expect(role.emotion).toBe('正常')
      }
    } finally {
      vi.restoreAllMocks()
    }
  })

  // MG4 regression guard: stop() resets isAudioPlaying so start() can replay.
  it('engine: stop resets isAudioPlaying so start() replays (MG4)', async () => {
    const { isAudioPlaying } = await import('@/composables/audio-queue')
    class FakeAudio {
      src = ''; muted = false; currentTime = 0
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      load() {}
      play() { return Promise.resolve() }
      pause() {}
    }
    // @ts-expect-error override Audio constructor
    globalThis.Audio = FakeAudio
    vi.spyOn(global, 'setTimeout').mockImplementation((fn: () => void) => {
      if (typeof fn === 'function') fn()
      return 0 as unknown as ReturnType<typeof setTimeout>
    })

    try {
      const store = useScriptStore()
      store.addLine(makeLine('s1', 0))
      _resetReplaySingleton()
      const replay = useA2DReplay()

      replay.start(0)
      expect(replay.state.value).toBe('playing')
      expect(isAudioPlaying.value).toBe(true)

      replay.stop()
      expect(replay.state.value).toBe('idle')
      // MG4: core of the fix — isAudioPlaying reset so next start() can play.
      expect(isAudioPlaying.value).toBe(false)

      // After reset, a fresh start() enqueues + starts playback again.
      replay.start(0)
      expect(isAudioPlaying.value).toBe(true)
    } finally {
      vi.restoreAllMocks()
    }
  })

  // MG5 regression guard: seek() resets isAudioPlaying so playback starts.
  it('engine: seek resets isAudioPlaying so playback starts (MG5)', async () => {
    const { isAudioPlaying, audioQueue } = await import('@/composables/audio-queue')
    class FakeAudio {
      src = ''; muted = false; currentTime = 0
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      load() {}
      play() { return Promise.resolve() }
      pause() {}
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
      store.addLine(makeLine('k1', 0))
      store.addLine(makeLine('k2', 1))
      store.addLine(makeLine('k3', 2))

      _resetReplaySingleton()
      const replay = useA2DReplay()
      replay.start(0)
      expect(isAudioPlaying.value).toBe(true)

      // MG5: seek resets isAudioPlaying so the new items actually play.
      replay.seek(2)
      expect(store.playingLineId).toBe('k3')
      // After seek, enqueueFromIndex must actually start playback for k3,
      // draining it from the queue. Before the fix, isAudioPlaying was left
      // true and enqueueFromIndex skipped playNextInQueue, leaving k3 stuck.
      await new Promise(r => origSetTimeout(r, 5))
      expect(replay.state.value).toBe('playing')
      expect(audioQueue.value.length).toBe(0) // k3 dequeued (playing)
      expect(isAudioPlaying.value).toBe(true)
    } finally {
      vi.restoreAllMocks()
    }
  })

  // task9: sprite_positions applied to gameRoles (AC-4 b-axis).
  it('engine: applySpritePositions writes offsetX/offsetY/scale to gameRoles (task9)', async () => {
    const gameStore = useGameStore()
    gameStore.importFromSnapshot({
      gameRoles: { 1: { roleId: 1, roleName: 'ema', emotion: '正常', originalEmotion: '正常', scale: 1, offsetX: 0, offsetY: 0, show: true } },
      presentRoleIds: [1],
    })

    const store = useScriptStore()
    const line: ScriptLine = {
      id: 'sp1', speaker: 'ema', display_text: '文本', tts_text: 'TTS', index: 0,
      audio_path: null, stage_id: '',
      overlay: { sprite_positions: { ema: { x: 30, y: 60, scale: 1.2 } } } as any,
    }

    _resetReplaySingleton()
    const replay = useA2DReplay()
    // Directly invoke the sprite application via the engine's public surface.
    replay.seek(0) // sets playingLineId; watch triggers applySpritePositions

    // Manually apply through a fresh start to exercise applySpritePositions.
    store.lines.length = 0
    store.lines.push(line as any)
    store.playingLineId = line.id
    // Trigger the watch by advancing.
    await new Promise(r => setTimeout(r, 10))

    // Sprite positions written to gameRoles[1].
    expect(gameStore.gameRoles[1].offsetX).toBe(30)
    expect(gameStore.gameRoles[1].offsetY).toBe(60)
    expect(gameStore.gameRoles[1].scale).toBe(1.2)
  })

  // AC-6 negative: pause→start must not double-queue (MG-DOUBLEQUEUE fix).
  it('engine: restart after pause does not double-queue (AC-6 negative)', async () => {
    const { audioQueue } = await import('@/composables/audio-queue')
    class FakeAudio {
      src = ''; muted = false; currentTime = 0
      onended: (() => void) | null = null
      onerror: (() => void) | null = null
      load() {}
      play() { return Promise.resolve() }
      pause() {}
    }
    // @ts-expect-error override Audio constructor
    globalThis.Audio = FakeAudio
    vi.spyOn(global, 'setTimeout').mockImplementation((fn: () => void) => {
      if (typeof fn === 'function') fn()
      return 0 as unknown as ReturnType<typeof setTimeout>
    })

    try {
      const store = useScriptStore()
      store.addLine(makeLine('d1', 0))
      store.addLine(makeLine('d2', 1))
      store.addLine(makeLine('d3', 2))

      _resetReplaySingleton()
      const replay = useA2DReplay()

      // Start + advance one line.
      replay.start(0)
      expect(replay.state.value).toBe('playing')
      await new Promise(r => setTimeout(r, 10))

      // Pause mid-replay (1 line already dequeued + playing, 2 remain in queue).
      replay.pause()
      const queueAfterPause = audioQueue.value.length // expect 2

      // AC-6 negative: restart must clear old queue + re-enqueue fresh,
      // NOT append duplicates on top of the paused remainder.
      replay.start(0)
      expect(replay.state.value).toBe('playing')
      // After restart: 3 re-enqueued, 1 dequeued by playNextInQueue = 2 remain.
      // WITHOUT the fix, restart appends 3 onto the existing 2 = 5 (then -1 = 4).
      expect(audioQueue.value.length).toBe(2)
      // Most importantly: no duplicates — restart queue equals paused queue size.
      expect(audioQueue.value.length).toBe(queueAfterPause)
    } finally {
      vi.restoreAllMocks()
    }
  })

  // AC-2 negative: empty script → idle + error (no crash).
  it('engine: empty script start returns idle with error (AC-2 negative)', () => {
    const store = useScriptStore()
    store.reset()
    _resetReplaySingleton()
    const replay = useA2DReplay()
    replay.start(0)
    expect(replay.state.value).toBe('idle')
    expect(replay.error.value).toBe('无内容可重播')
  })

  // AC-2 negative: out-of-range index → no-op.
  it('engine: out-of-range start index is a no-op (AC-2 negative)', () => {
    const store = useScriptStore()
    store.addLine(makeLine('o1', 0))
    _resetReplaySingleton()
    const replay = useA2DReplay()
    replay.start(5) // beyond lines.length
    expect(replay.state.value).toBe('idle')
    expect(store.playingLineId).toBeNull()
  })

  // AC-4 positive: BGM switches when line has overlay.bgm.
  it('engine: applyBGM plays bgm when line has overlay.bgm (AC-4 positive)', () => {
    const store = useScriptStore()
    const line: ScriptLine = {
      id: 'bg1', speaker: 'ema', display_text: 't', tts_text: 't', index: 0,
      audio_path: '/audio/bg1.wav', stage_id: '',
      overlay: { bgm: 'bgm.mp3', bgm_volume: 0.5, bgm_loop: true } as any,
    }
    store.lines.push(line as any)
    _resetReplaySingleton()
    const replay = useA2DReplay()
    replay.start(0)
    // After start, applyBGM should have played the bgm.
    expect(getCurrentBGM()).toBe('bgm.mp3')
  })

  // AC-4 negative: empty bgm stops playback.
  it('engine: applyBGM stops bgm when line has no bgm (AC-4 negative)', () => {
    const store = useScriptStore()
    // First play a bgm directly.
    playBGM('existing.mp3')
    expect(getCurrentBGM()).toBe('existing.mp3')
    // Now start replay with a line that has no bgm.
    const line: ScriptLine = {
      id: 'nb1', speaker: 'ema', display_text: 't', tts_text: 't', index: 0,
      audio_path: '/audio/nb1.wav', stage_id: '', overlay: null,
    }
    store.lines.push(line as any)
    _resetReplaySingleton()
    const replay = useA2DReplay()
    replay.start(0)
    expect(getCurrentBGM()).toBe('')
  })

  // AC-5 positive: toast fires when pendingLiveQueue drains on replay end.
  it('engine: toast fires with count when live TTS queued during replay (AC-5 positive)', async () => {
    const { pendingLiveQueue, isAudioPlaying } = await import('@/composables/audio-queue')
    const { setReplayActive } = await import('@/composables/useA2DWebSocket')
    const uiStore = (await import('@/stores/modules/ui/ui')).useUIStore()
    const showInfoSpy = vi.spyOn(uiStore, 'showInfo')

    // Simulate live TTS arriving mid-replay: queued into pendingLiveQueue.
    pendingLiveQueue.value = [{ url: '/audio/live1.wav', lineId: 'live1' }, { url: '/audio/live2.wav', lineId: 'live2' }]

    // Simulate replay end: isAudioPlaying false -> drain triggers.
    isAudioPlaying.value = false
    setReplayActive(false)

    expect(showInfoSpy).toHaveBeenCalledWith(expect.objectContaining({ message: expect.stringContaining('2') }))
    showInfoSpy.mockRestore()
  })

  // AC-5 negative: live TTS arriving mid-replay routes to pending queue via the
  // real routing guard (routeLiveAudio), does NOT interrupt replay audio.
  it('engine: live TTS mid-replay routes to pending queue, not active queue (AC-5 negative)', async () => {
    const { pendingLiveQueue, audioQueue } = await import('@/composables/audio-queue')
    const { routeLiveAudio, setReplayActive } = await import('@/composables/useA2DWebSocket')
    const store = useScriptStore()
    store.addLine(makeLine('r1', 0))
    _resetReplaySingleton()
    const replay = useA2DReplay()
    replay.start(0) // sets replayActive = true
    const activeQueueLen = audioQueue.value.length

    // Drive the REAL routing guard with replay active.
    routeLiveAudio('http://host/audio/live.wav', 'live1', true)
    expect(audioQueue.value.length).toBe(activeQueueLen) // active queue untouched
    expect(pendingLiveQueue.value.length).toBe(1) // deferred
    expect(pendingLiveQueue.value[0].lineId).toBe('live1')

    // AC-5 corollary: with replay inactive, same item routes to active queue.
    setReplayActive(false)
    routeLiveAudio('http://host/audio/live2.wav', 'live2', false)
    expect(audioQueue.value.length).toBe(activeQueueLen + 1) // enqueued for playback
  })

  // AC-5: subtitle-timer drives silent lines (narrator without audio).
  it('engine: silent first line advances via subtitle-timer (AC-5)', async () => {
    // Capture timer callback without firing it.
    let timerFn: (() => void) | null = null
    vi.spyOn(global, 'setTimeout').mockImplementation((fn: () => void) => {
      timerFn = fn // capture but don't fire
      return 0 as unknown as ReturnType<typeof setTimeout>
    })

    try {
      const store = useScriptStore()
      // First line is silent narrator, second has audio (passes hasAnyAudio guard).
      store.addLine(makeLine('n1', 0, { speaker: 'narrator', audio_path: null, display_text: '旁白文本' }))
      store.addLine(makeLine('a1', 1, { audio_path: '/audio/a1.wav' }))

      _resetReplaySingleton()
      const replay = useA2DReplay()
      replay.start(0)

      // Timer should be registered for the silent FIRST line.
      expect(timerFn).not.toBeNull()
      expect(replay.state.value).toBe('playing')
      expect(store.playingLineId).toBe('n1')

      // Manually fire the timer → advance() → moves to a1 (audio) AND starts audio queue.
      timerFn!()
      expect(store.playingLineId).toBe('a1')
      // After advancing to audio line, audioQueue should start draining (isAudioPlaying).
      expect(isAudioPlaying.value).toBe(true)
    } finally {
      vi.restoreAllMocks()
    }
  })

  // AC-5: pause freezes subtitle-timer, resume rebuilds it.
  it('engine: pause freezes subtitle-timer, resume rebuilds (AC-5)', async () => {
    let timerCount = 0
    vi.spyOn(global, 'setTimeout').mockImplementation((_fn: () => void) => {
      timerCount++
      return 0 as unknown as ReturnType<typeof setTimeout>
    })

    try {
      const store = useScriptStore()
      // Silent first line (timer set), audio second (guard).
      store.addLine(makeLine('n1', 0, { speaker: 'narrator', audio_path: null, display_text: '旁白' }))
      store.addLine(makeLine('a1', 1, { audio_path: '/audio/a1.wav' }))

      _resetReplaySingleton()
      const replay = useA2DReplay()
      replay.start(0)

      // One timer registered for silent line.
      expect(timerCount).toBe(1)

      // Pause — timer cleared (no new timer yet).
      replay.pause()
      expect(replay.state.value).toBe('paused')

      // Resume — timer rebuilt for current silent line.
      replay.resume()
      expect(replay.state.value).toBe('playing')
      expect(timerCount).toBe(2) // rebuilt
    } finally {
      vi.restoreAllMocks()
    }
  })
})
