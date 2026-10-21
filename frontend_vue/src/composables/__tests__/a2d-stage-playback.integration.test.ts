import { flushPromises, mount } from '@vue/test-utils'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import GameRoleAvatar from '@/components/game/standard/GameRoleAvatar.vue'
import { useGameStore } from '@/stores/modules/game'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { audioQueue } from '@/composables/audio-queue'
import { _resetReplaySingleton, useA2DReplay } from '@/composables/useA2DReplay'
import { _resetStageActions } from '@/composables/a2d-stage-actions'

const audioEndHandlers: Array<(() => void) | null> = []
const originalAudio = globalThis.Audio

class FakeAudio {
  src = ''
  muted = false
  currentTime = 0
  onerror: (() => void) | null = null

  load(): void {}
  play(): Promise<void> {
    return Promise.resolve()
  }
  pause(): void {}

  set onended(handler: (() => void) | null) {
    audioEndHandlers.push(handler)
  }
}

function makeLine(id: string, index: number, emotion: string): ScriptLine {
  return {
    id,
    speaker: 'ema',
    emotion,
    display_text: `字幕 ${id}`,
    tts_text: `语音 ${id}`,
    index,
    audio_path: `/audio/${id}.wav`,
    overlay: null,
    stage_id: '',
  }
}

function makeRole() {
  return {
    roleId: 1,
    scriptRoleKey: 'ema',
    roleName: 'ema',
    roleSubTitle: '',
    thinkMessage: '',
    emotion: '正常',
    originalEmotion: '正常',
    scale: 1,
    offsetY: 0,
    offsetX: 0,
    bubbleTop: 5,
    bubbleLeft: 20,
    show: true,
    clothes: {},
    clothesName: 'default',
    bodyPart: {},
    character_folder: '',
  }
}

describe('A2D stage actions hold replay subtitles through the real avatar component', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    audioQueue.value = []
    audioEndHandlers.length = 0
    _resetReplaySingleton()
    _resetStageActions()
    globalThis.Audio = FakeAudio as unknown as typeof Audio
    vi.spyOn(HTMLMediaElement.prototype, 'play').mockResolvedValue(undefined)
    vi.spyOn(HTMLMediaElement.prototype, 'load').mockImplementation(() => {})
  })

  afterEach(() => {
    _resetReplaySingleton()
    _resetStageActions()
    globalThis.Audio = originalAudio
    vi.useRealTimers()
    vi.restoreAllMocks()
  })

  it('waits for both emotion animation and bubble transition before showing the next line', async () => {
    vi.useFakeTimers()
    const gameStore = useGameStore()
    const role = makeRole()
    gameStore.gameRoles[1] = role
    gameStore.presentRoleIds = [1]

    const scriptStore = useScriptStore()
    scriptStore.addLine(makeLine('action-line', 0, '高兴'))
    scriptStore.addLine(makeLine('next-line', 1, '正常'))

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
    await flushPromises()

    const replay = useA2DReplay()
    replay.start(0)
    await flushPromises()
    await vi.advanceTimersByTimeAsync(500)
    await flushPromises()

    expect(audioEndHandlers[0]).toBeTypeOf('function')
    audioEndHandlers[0]?.()
    await flushPromises()
    expect(replay.currentSubtitle.value).toBe('字幕 action-line')

    await avatar.get('.happy-bounce').trigger('animationend', { animationName: 'happyBounce' })
    await flushPromises()
    expect(replay.currentSubtitle.value).toBe('字幕 action-line')

    await vi.advanceTimersByTimeAsync(2000)
    const transitionEnd = new Event('transitionend', { bubbles: true })
    Object.defineProperty(transitionEnd, 'propertyName', { value: 'opacity' })
    avatar.get('.bubble').element.dispatchEvent(transitionEnd)
    await flushPromises()

    expect(replay.currentSubtitle.value).toBe('字幕 next-line')
    expect(scriptStore.playingLineId).toBe('next-line')

    replay.stop()
    avatar.unmount()
  })
})
