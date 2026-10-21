import { mount } from '@vue/test-utils'
import { nextTick } from 'vue'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ReviewPanel from '../ReviewPanel.vue'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'

const mocks = vi.hoisted(() => ({
  emitTrace: vi.fn(),
  sendStart: vi.fn(),
  sendContinue: vi.fn(),
  sendRetry: vi.fn(),
  sendRegenerateTTS: vi.fn(),
  logUserAction: vi.fn(),
  downloadSafeTrace: vi.fn(),
  replay: {
    isPlaying: { value: false },
    isPaused: { value: false },
    error: { value: null as string | null },
    missingAudioLines: { value: [] as string[] },
    silentLines: { value: [] as string[] },
    start: vi.fn(),
    pause: vi.fn(),
    resume: vi.fn(),
    stop: vi.fn(),
  },
}))

vi.mock('@/utils/a2d-trace', () => ({
  emitTrace: mocks.emitTrace,
  downloadSafeTrace: mocks.downloadSafeTrace,
}))

vi.mock('@/composables/useA2DWebSocket', () => ({
  useA2DWebSocket: () => mocks,
}))

vi.mock('@/composables/useA2DReplay', () => ({
  useA2DReplay: () => mocks.replay,
}))

vi.mock('@/composables/useA2DSaveLoad', () => ({
  exportSession: vi.fn(),
  importSession: vi.fn(),
  commitImport: vi.fn(),
}))

function makeLine(id: string, displayText: string, index: number): ScriptLine {
  return {
    id,
    speaker: 'ema',
    display_text: displayText,
    tts_text: displayText,
    index,
    audio_path: `/audio/${id}.wav`,
    overlay: null,
    stage_id: '',
  }
}

describe('ReviewPanel playback preview', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.replay.isPlaying.value = false
    mocks.replay.isPaused.value = false
    mocks.replay.error.value = null
    mocks.replay.missingAudioLines.value = []
    mocks.replay.silentLines.value = []
    vi.clearAllMocks()
  })

  it('keeps the preview on the playing sentence until playback advances', async () => {
    const store = useScriptStore()
    const playingLine = makeLine('line-1', '正在播放的这一句。', 0)
    store.addLine(playingLine)
    store.setPhase('thinking')
    store.setPhase('synthesizing')
    store.playingLineId = playingLine.id
    store.isAudioPlaying = true
    store.setPhase('thinking')
    store.addLine(makeLine('line-2', '刚生成、还没播放的下一句。', 1))

    const wrapper = mount(ReviewPanel)

    expect(wrapper.get('.preview-text').text()).toBe('正在播放的这一句。')

    store.playingLineId = 'line-2'
    await nextTick()

    expect(wrapper.get('.preview-text').text()).toBe('刚生成、还没播放的下一句。')
  })

  it('shows the latest generated sentence when no playback line has started', () => {
    const store = useScriptStore()
    store.setPhase('thinking')
    store.addLine(makeLine('line-1', '刚生成、等待播放的第一句。', 0))

    const wrapper = mount(ReviewPanel)

    expect(wrapper.get('.preview-text').text()).toBe('刚生成、等待播放的第一句。')
  })

  it('offers a safe timing trace download during generation', async () => {
    const store = useScriptStore()
    store.setPhase('thinking')
    const wrapper = mount(ReviewPanel)

    await wrapper.get('.diagnostics-button').trigger('click')

    expect(mocks.downloadSafeTrace).toHaveBeenCalledOnce()
  })

  it('records when the generation preview stops showing a line', async () => {
    const store = useScriptStore()
    store.setPhase('thinking')
    store.addLine(makeLine('line-1', 'private dialogue', 0))
    const wrapper = mount(ReviewPanel)
    mocks.emitTrace.mockClear()

    store.setPhase('idle')
    await nextTick()

    expect(mocks.emitTrace).toHaveBeenCalledWith('review_preview_hide', {
      lineId: 'line-1',
      index: 0,
    })
    expect(JSON.stringify(mocks.emitTrace.mock.calls)).not.toContain('private dialogue')
    wrapper.unmount()
  })
})
