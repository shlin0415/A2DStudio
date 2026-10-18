import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import ScriptEditorPanel from '../ScriptEditorPanel.vue'
import { useScriptStore } from '@/stores/modules/script'

const mocks = vi.hoisted(() => ({
  sendRegenerateTTS: vi.fn(),
  availableSpeakers: { value: ['ema', 'hiro'] as string[] },
  isInitialized: { value: true },
}))

vi.mock('@/composables/useA2DWebSocket', async () => {
  const { ref } = await import('vue')
  return {
    useA2DWebSocket: () => ({
      sendRegenerateTTS: mocks.sendRegenerateTTS,
      availableSpeakers: ref(mocks.availableSpeakers.value),
      isInitialized: ref(mocks.isInitialized.value),
    }),
  }
})

describe('ScriptEditorPanel', () => {
  beforeEach(() => {
    setActivePinia(createPinia())
    mocks.sendRegenerateTTS.mockReset()
    mocks.availableSpeakers.value = ['ema', 'hiro']
    mocks.isInitialized.value = true
  })

  it('creates and edits a line for a selected speaker', async () => {
    const wrapper = mount(ScriptEditorPanel)
    const store = useScriptStore()

    await wrapper.get('[data-testid="add-hiro-line"]').trigger('click')
    const line = store.lines[0]
    await wrapper.get(`[data-testid="line-text-${line.id}"]`).setValue('你好，今天也一起努力吧。')

    expect(line.speaker).toBe('hiro')
    expect(line.display_text).toBe('你好，今天也一起努力吧。')
    expect(line.tts_text).toBe('你好，今天也一起努力吧。')
  })

  it('keeps spaces while editing the project title', async () => {
    const wrapper = mount(ScriptEditorPanel)
    const titleInput = wrapper.get('[aria-label="项目名称"]')

    await titleInput.setValue('A short story')

    expect(useScriptStore().projectName).toBe('A short story')
  })

  it('requests synthesis with the line speaker and speech text', async () => {
    const store = useScriptStore()
    const line = store.createManualLine('ema')
    store.updateLine(line.id, { display_text: '早上好。', tts_text: '早上好。' })
    const wrapper = mount(ScriptEditorPanel)

    await wrapper.get(`[data-testid="synthesize-${line.id}"]`).trigger('click')

    expect(mocks.sendRegenerateTTS).toHaveBeenCalledWith(line.id, '早上好。', 'ema', false)
  })

  it('disables synthesis when the selected speaker has no local voice configuration', async () => {
    mocks.availableSpeakers.value = ['ema']
    const store = useScriptStore()
    const line = store.createManualLine('hiro')
    store.updateLine(line.id, { tts_text: '你好。' })
    const wrapper = mount(ScriptEditorPanel)

    expect(await wrapper.get(`[data-testid="synthesize-${line.id}"]`).isDisabled()).toBe(true)
  })
})
