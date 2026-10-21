// AC-6: Narrator lines render with narrator style (centered, gray, bubble-free).
import { describe, it, expect, vi } from 'vitest'
import { mount } from '@vue/test-utils'
import SubtitleOverlay from '../SubtitleOverlay.vue'

const emitTrace = vi.hoisted(() => vi.fn())

vi.mock('@/utils/a2d-trace', () => ({ emitTrace }))

describe('SubtitleOverlay narrator styling (AC-6)', () => {
  it('applies narrator class when isNarrator is true', () => {
    const wrapper = mount(SubtitleOverlay, {
      props: { text: '旁白文本', isNarrator: true },
    })
    expect(wrapper.find('.subtitle-overlay__text--narrator').exists()).toBe(true)
  })

  it('does NOT apply narrator class when isNarrator is false', () => {
    const wrapper = mount(SubtitleOverlay, {
      props: { text: '对话文本', isNarrator: false },
    })
    expect(wrapper.find('.subtitle-overlay__text--narrator').exists()).toBe(false)
  })

  it('does NOT apply narrator class when isNarrator is undefined (default)', () => {
    const wrapper = mount(SubtitleOverlay, {
      props: { text: '对话文本' },
    })
    expect(wrapper.find('.subtitle-overlay__text--narrator').exists()).toBe(false)
  })

  it('renders the text content', () => {
    const wrapper = mount(SubtitleOverlay, {
      props: { text: 'hello' },
    })
    expect(wrapper.text()).toContain('hello')
  })

  it('renders nothing when text is empty', () => {
    const wrapper = mount(SubtitleOverlay, {
      props: { text: '' },
    })
    expect(wrapper.find('.subtitle-overlay').exists()).toBe(false)
  })

  it('records only line metadata when a subtitle appears and changes', async () => {
    const wrapper = mount(SubtitleOverlay, {
      props: { text: 'private dialogue', lineId: 'line-1', lineIndex: 0 },
    })

    expect(emitTrace).toHaveBeenLastCalledWith('subtitle_show', {
      lineId: 'line-1',
      lineIndex: 0,
      characterCount: 16,
    })

    await wrapper.setProps({ text: 'second line', lineId: 'line-2', lineIndex: 1 })

    expect(emitTrace).toHaveBeenNthCalledWith(2, 'subtitle_hide', { lineId: 'line-1' })
    expect(emitTrace).toHaveBeenLastCalledWith('subtitle_show', {
      lineId: 'line-2',
      lineIndex: 1,
      characterCount: 11,
    })
    expect(emitTrace.mock.calls.flat()).not.toContain('private dialogue')
  })

  it('records subtitle hide when replay stops', async () => {
    const wrapper = mount(SubtitleOverlay, {
      props: { text: 'line text', lineId: 'line-1', lineIndex: 0 },
    })
    emitTrace.mockClear()

    await wrapper.setProps({ text: '', lineId: null, lineIndex: null })

    expect(emitTrace).toHaveBeenCalledWith('subtitle_hide', { lineId: 'line-1' })
  })
})
