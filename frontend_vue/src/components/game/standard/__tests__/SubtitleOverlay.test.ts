// AC-6: Narrator lines render with narrator style (centered, gray, bubble-free).
import { describe, it, expect } from 'vitest'
import { mount } from '@vue/test-utils'
import SubtitleOverlay from '../SubtitleOverlay.vue'

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
})
