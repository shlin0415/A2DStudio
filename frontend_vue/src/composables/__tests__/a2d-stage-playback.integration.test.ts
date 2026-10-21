import { flushPromises, mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { defineComponent, h } from 'vue'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import GameRoleAvatar from '@/components/game/standard/GameRoleAvatar.vue'
import ReviewPanel from '@/components/game/ReviewPanel.vue'
import { audioQueue, isAudioPlaying, pendingLiveQueue } from '@/composables/audio-queue'
import { _resetStageActions } from '@/composables/a2d-stage-actions'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'
import { useGameStore } from '@/stores/modules/game'
import { useScriptStore } from '@/stores/modules/script'

const audioEndHandlers: Array<(() => void) | null> = []
const originalAudio = globalThis.Audio
const originalWebSocket = globalThis.WebSocket
let activeSocket: FakeWebSocket | null = null
const mountedWrappers: Array<{ unmount: () => void }> = []

class FakeAudio {
  static instances: FakeAudio[] = []

  src = ''
  muted = false
  currentTime = 0
  onerror: (() => void) | null = null
  playCalls = 0
  pauseCalls = 0

  constructor() {
    FakeAudio.instances.push(this)
  }

  load(): void {}
  play(): Promise<void> {
    this.playCalls += 1
    return Promise.resolve()
  }
  pause(): void {
    this.pauseCalls += 1
  }

  set onended(handler: (() => void) | null) {
    audioEndHandlers.push(handler)
  }
}

class FakeWebSocket {
  static readonly OPEN = 1
  static readonly CONNECTING = 0

  readonly readyState = FakeWebSocket.OPEN
  onopen: (() => void) | null = null
  onmessage: ((event: MessageEvent) => void) | null = null
  onclose: (() => void) | null = null
  onerror: ((event: Event) => void) | null = null

  constructor() {
    activeSocket = this
  }

  send(): void {}
  close(): void {
    this.onclose?.()
  }
}

function sendSocketMessage(type: string, payload: Record<string, unknown>): void {
  if (!activeSocket?.onmessage) throw new Error('WebSocket message handler is not ready')
  activeSocket.onmessage({ data: JSON.stringify({ type, payload }) } as MessageEvent)
}

function scriptLine(id: string, index: number, emotion: string): Record<string, unknown> {
  return {
    id,
    speaker: 'ema',
    emotion,
    display_text: `字幕 ${id}`,
    tts_text: `语音 ${id}`,
    index,
    audio_path: null,
    overlay: null,
    stage_id: '',
  }
}

describe('A2D generated playback holds preview through the real avatar actions', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    FakeAudio.instances = []
    audioQueue.value = []
    pendingLiveQueue.value = []
    isAudioPlaying.value = false
    audioEndHandlers.length = 0
    activeSocket = null
    mountedWrappers.length = 0
    globalThis.Audio = FakeAudio as unknown as typeof Audio
    globalThis.WebSocket = FakeWebSocket as unknown as typeof WebSocket
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
    vi.spyOn(console, 'log').mockImplementation(() => {})
  })

  afterEach(() => {
    mountedWrappers.reverse().forEach((wrapper) => wrapper.unmount())
    websocketClient?.disconnect()
    websocketClient = null
    _resetStageActions()
    audioQueue.value = []
    pendingLiveQueue.value = []
    isAudioPlaying.value = false
    globalThis.Audio = originalAudio
    globalThis.WebSocket = originalWebSocket
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  let websocketClient: ReturnType<typeof useA2DWebSocket> | null = null

  it('targets the imported project role after server role IDs are replaced', async () => {
    vi.useFakeTimers()

    const WebSocketHarness = defineComponent({
      setup() {
        websocketClient = useA2DWebSocket()
        return () => h('div')
      },
    })
    const socketHarness = mount(WebSocketHarness)
    mountedWrappers.push(socketHarness)
    sendSocketMessage('a2d.characters', {
      characters: [{ roleId: 1, script_role_key: 'ema', roleName: 'ema' }],
    })

    const gameStore = useGameStore()
    const runtimeRoleId = -1_000_000
    const projectRole = {
      ...gameStore.gameRoles[1]!,
      roleId: runtimeRoleId,
      roleName: '艾玛',
      emotion: '高兴',
      originalEmotion: '高兴',
    }
    gameStore.importFromSnapshot({
      gameRoles: { [runtimeRoleId]: projectRole },
      presentRoleIds: [runtimeRoleId],
    })
    expect(Object.keys(gameStore.gameRoles)).toEqual([String(runtimeRoleId)])

    const avatar = mount(GameRoleAvatar, {
      props: { role: gameStore.gameRoles[runtimeRoleId]! },
      global: {
        stubs: {
          TouchAreas: true,
          ImageAcrossFade: {
            props: ['src'],
            template: '<div data-testid="avatar-image" />',
            methods: { waitForLoad: () => Promise.resolve() },
          },
        },
      },
    })
    mountedWrappers.push(avatar)
    const review = mount(ReviewPanel)
    mountedWrappers.push(review)
    await flushPromises()

    const scriptStore = useScriptStore()
    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('project-line', 0, '高兴'))
    sendSocketMessage('status', { phase: 'synthesizing' })
    sendSocketMessage('tts_ready', { id: 'project-line', audio_path: '/audio/project-line.wav' })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()

    expect(gameStore.gameRoles[runtimeRoleId]!.emotion).toBe('高兴')

    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('next-line', 1, '高兴'))
    sendSocketMessage('status', { phase: 'synthesizing' })
    sendSocketMessage('tts_ready', { id: 'next-line', audio_path: '/audio/next-line.wav' })
    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('third-line', 2, '正常'))
    sendSocketMessage('status', { phase: 'synthesizing' })
    sendSocketMessage('tts_ready', { id: 'third-line', audio_path: '/audio/third-line.wav' })
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 project-line')

    audioEndHandlers[0]?.()
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 project-line')

    await avatar.get('.happy-bounce').trigger('animationend', { animationName: 'happyBounce' })
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 project-line')

    await vi.advanceTimersByTimeAsync(2000)
    const transitionEnd = new Event('transitionend', { bubbles: true })
    Object.defineProperty(transitionEnd, 'propertyName', { value: 'opacity' })
    avatar.get('.bubble').element.dispatchEvent(transitionEnd)
    await flushPromises()

    expect(review.get('.preview-text').text()).toBe('字幕 next-line')
    expect(scriptStore.playingLineId).toBe('next-line')

    await vi.advanceTimersByTimeAsync(200)
    await flushPromises()
    audioEndHandlers[1]?.()
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 next-line')

    await avatar.get('.happy-bounce').trigger('animationend', { animationName: 'happyBounce' })
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 next-line')

    await vi.advanceTimersByTimeAsync(2000)
    const nextTransitionEnd = new Event('transitionend', { bubbles: true })
    Object.defineProperty(nextTransitionEnd, 'propertyName', { value: 'opacity' })
    avatar.get('.bubble').element.dispatchEvent(nextTransitionEnd)
    await flushPromises()

    expect(review.get('.preview-text').text()).toBe('字幕 third-line')
    expect(scriptStore.playingLineId).toBe('third-line')
  })

  it('keeps the generated line visible until its audio, emotion animation, and bubble finish', async () => {
    vi.useFakeTimers()

    const WebSocketHarness = defineComponent({
      setup() {
        websocketClient = useA2DWebSocket()
        return () => h('div')
      },
    })
    const socketHarness = mount(WebSocketHarness)
    mountedWrappers.push(socketHarness)
    sendSocketMessage('a2d.characters', {
      characters: [{ roleId: 1, script_role_key: 'ema', roleName: 'ema' }],
    })

    const gameStore = useGameStore()
    const role = gameStore.gameRoles[1]!
    const avatar = mount(GameRoleAvatar, {
      props: { role },
      global: {
        stubs: {
          TouchAreas: true,
          ImageAcrossFade: {
            props: ['src'],
            template: '<div data-testid="avatar-image" />',
            methods: { waitForLoad: () => Promise.resolve() },
          },
        },
      },
    })
    mountedWrappers.push(avatar)
    const review = mount(ReviewPanel)
    mountedWrappers.push(review)
    await flushPromises()

    const scriptStore = useScriptStore()
    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('action-line', 0, '高兴'))
    sendSocketMessage('status', { phase: 'synthesizing' })
    sendSocketMessage('tts_ready', { id: 'action-line', audio_path: '/audio/action-line.wav' })
    await flushPromises()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()

    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('next-line', 1, '正常'))
    sendSocketMessage('status', { phase: 'synthesizing' })
    sendSocketMessage('tts_ready', { id: 'next-line', audio_path: '/audio/next-line.wav' })
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 action-line')

    expect(audioEndHandlers[0]).toBeTypeOf('function')
    audioEndHandlers[0]?.()
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 action-line')

    await avatar.get('.happy-bounce').trigger('animationend', { animationName: 'happyBounce' })
    await flushPromises()
    expect(review.get('.preview-text').text()).toBe('字幕 action-line')

    await vi.advanceTimersByTimeAsync(2000)
    const transitionEnd = new Event('transitionend', { bubbles: true })
    Object.defineProperty(transitionEnd, 'propertyName', { value: 'opacity' })
    avatar.get('.bubble').element.dispatchEvent(transitionEnd)
    await flushPromises()

    expect(review.get('.preview-text').text()).toBe('字幕 next-line')
    expect(scriptStore.playingLineId).toBe('next-line')
  })

  it('rolls back failed batch lines and their queued audio on error', async () => {
    const WebSocketHarness = defineComponent({
      setup() {
        websocketClient = useA2DWebSocket()
        return () => h('div')
      },
    })
    const harness = mount(WebSocketHarness)
    mountedWrappers.push(harness)
    await flushPromises()

    const store = useScriptStore()
    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('kept-line', 0, '正常'))
    sendSocketMessage('script_line', scriptLine('failed-line', 1, '正常'))
    store.playingLineId = 'failed-line'
    store.isAudioPlaying = true
    audioQueue.value = [
      { url: '/audio/failed.wav', lineId: 'failed-line' },
      { url: '/audio/kept.wav', lineId: 'kept-audio' },
    ]
    pendingLiveQueue.value = [{ url: '/audio/deferred.wav', lineId: 'failed-line' }]
    isAudioPlaying.value = true

    sendSocketMessage('error', {
      error_type: 'unknown',
      message: 'generation failed',
      detail: '',
      generation_id: '',
      retry_count: 0,
      max_retries: 3,
      line_ids: ['failed-line'],
    })

    expect(store.lines.map((line) => line.id)).toEqual(['kept-line'])
    expect(audioQueue.value.map((item) => item.lineId)).toEqual(['kept-audio'])
    expect(pendingLiveQueue.value).toEqual([])
    expect(isAudioPlaying.value).toBe(false)
    expect(store.isAudioPlaying).toBe(false)
    expect(store.playingLineId).toBeNull()
    expect(store.error?.line_ids).toEqual(['failed-line'])
  })

  it('keeps earlier valid playback running when a later batch is rolled back', async () => {
    const WebSocketHarness = defineComponent({
      setup() {
        websocketClient = useA2DWebSocket()
        return () => h('div')
      },
    })
    const harness = mount(WebSocketHarness)
    mountedWrappers.push(harness)
    await flushPromises()

    const store = useScriptStore()
    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('kept-line', 0, '正常'))
    sendSocketMessage('script_line', scriptLine('failed-line', 1, '正常'))
    store.playingLineId = 'kept-line'
    store.isAudioPlaying = true
    isAudioPlaying.value = true

    sendSocketMessage('error', {
      error_type: 'unknown',
      message: 'generation failed',
      detail: '',
      generation_id: '',
      retry_count: 0,
      max_retries: 3,
      line_ids: ['failed-line'],
    })

    expect(store.lines.map((line) => line.id)).toEqual(['kept-line'])
    expect(isAudioPlaying.value).toBe(true)
    expect(store.isAudioPlaying).toBe(true)
    expect(store.playingLineId).toBe('kept-line')
  })

  it('does not start a rolled-back line after its audio pre-roll is cancelled', async () => {
    vi.useFakeTimers()
    const WebSocketHarness = defineComponent({
      setup() {
        websocketClient = useA2DWebSocket()
        return () => h('div')
      },
    })
    const harness = mount(WebSocketHarness)
    mountedWrappers.push(harness)
    await flushPromises()

    sendSocketMessage('status', { phase: 'thinking' })
    sendSocketMessage('script_line', scriptLine('failed-line', 0, '正常'))
    sendSocketMessage('tts_ready', {
      id: 'failed-line',
      audio_path: '/audio/failed.wav',
      tts_text: '语音 failed-line',
    })
    await flushPromises()

    const audio = FakeAudio.instances.find((instance) => instance.src.endsWith('/audio/failed.wav'))
    expect(audio).toBeDefined()
    sendSocketMessage('error', {
      error_type: 'unknown',
      message: 'generation failed',
      detail: '',
      generation_id: '',
      retry_count: 0,
      max_retries: 3,
      line_ids: ['failed-line'],
    })
    await vi.advanceTimersByTimeAsync(600)

    expect(audio?.playCalls).toBe(1)
    expect(audio?.pauseCalls).toBe(1)
  })
})
