import { mount } from '@vue/test-utils'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import StageView from '../StageView.vue'

const mocks = vi.hoisted(() => ({
  scriptStore: {
    lines: [] as Array<{ id: string; index?: number }>,
    selectedLineId: '',
    selectedLine: null as { id: string; index?: number } | null,
    playingLineId: null as string | null,
    stageMap: {} as Record<string, string>,
  },
  settingsStore: {
    currentBackground: '',
    setCurrentBackground: vi.fn(),
  },
  replay: {
    currentSubtitle: '',
    isPlaying: { value: false },
    isPaused: { value: false },
    error: { value: null as string | null },
    start: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    stop: vi.fn(),
  },
}))

vi.mock('@/composables/useA2DWebSocket', () => ({
  useA2DWebSocket: vi.fn(),
}))

vi.mock('@/composables/useA2DReplay', () => ({
  useA2DReplay: () => mocks.replay,
}))

vi.mock('@/stores/modules/script', () => ({
  useScriptStore: () => mocks.scriptStore,
}))

vi.mock('@/stores/modules/settings', () => ({
  useSettingsStore: () => mocks.settingsStore,
}))

vi.mock('@/composables/overlay-resolve', () => ({
  resolveVisual: () => null,
}))

vi.mock('@/composables/useA2DSaveLoad', () => ({
  commitImport: vi.fn(),
}))

function mountStageView() {
  return mount(StageView, {
    global: {
      stubs: {
        GameBackground: true,
        GameRolesStage: true,
        GameDialog: {
          template: '<div data-testid="legacy-chat-dialog" />',
        },
        StageOverlay: true,
        SubtitleOverlay: {
          props: ['text', 'lineId', 'lineIndex', 'isNarrator'],
          template: '<div data-testid="subtitle" :data-line-id="lineId" :data-line-index="lineIndex">{{ text }}</div>',
        },
        ScriptPanel: {
          template: '<div data-testid="script-panel" />',
        },
      },
    },
  })
}

describe('StageView', () => {
  beforeEach(() => {
    mocks.scriptStore.lines = []
    mocks.scriptStore.selectedLineId = ''
    mocks.scriptStore.selectedLine = null
    mocks.scriptStore.playingLineId = null
    mocks.replay.isPlaying.value = false
    mocks.replay.isPaused.value = false
    mocks.replay.error.value = null
    mocks.replay.start.mockReset()
    mocks.replay.pause.mockReset()
    mocks.replay.resume.mockReset()
    mocks.replay.stop.mockReset()
  })

  it('does not render the legacy chat dialog on the A2D stage', () => {
    const wrapper = mountStageView()

    expect(wrapper.find('[data-testid="legacy-chat-dialog"]').exists()).toBe(false)
  })

  it('enters focused playback without starting audio automatically', async () => {
    const wrapper = mountStageView()

    await wrapper.get('[data-testid="enter-focused-playback"]').trigger('click')

    expect(wrapper.get('[data-testid="script-panel"]').isVisible()).toBe(false)
    expect(wrapper.find('[data-testid="focused-playback-controls"]').exists()).toBe(true)
    expect(mocks.replay.start).not.toHaveBeenCalled()
  })

  it('starts from the selected line only after the play button is pressed', async () => {
    mocks.scriptStore.lines = [{ id: 'line-1' }, { id: 'line-2' }]
    mocks.scriptStore.selectedLineId = 'line-2'
    const wrapper = mountStageView()

    await wrapper.get('[data-testid="enter-focused-playback"]').trigger('click')
    await wrapper.get('[data-testid="focus-play"]').trigger('click')

    expect(mocks.replay.start).toHaveBeenCalledWith(1)
  })

  it('passes the active line identity to the subtitle layer for timing traces', () => {
    mocks.scriptStore.lines = [{ id: 'line-1', index: 3 }]
    mocks.scriptStore.playingLineId = 'line-1'
    const wrapper = mountStageView()

    expect(wrapper.get('[data-testid="subtitle"]').attributes('data-line-id')).toBe('line-1')
    expect(wrapper.get('[data-testid="subtitle"]').attributes('data-line-index')).toBe('3')
  })

  it('stops playback and returns to editing when focused playback is exited', async () => {
    const wrapper = mountStageView()

    await wrapper.get('[data-testid="enter-focused-playback"]').trigger('click')
    await wrapper.get('[data-testid="leave-focused-playback"]').trigger('click')

    expect(mocks.replay.stop).toHaveBeenCalledOnce()
    expect(wrapper.get('[data-testid="script-panel"]').isVisible()).toBe(true)
  })
})
