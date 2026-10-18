import { mount } from '@vue/test-utils'
import { describe, expect, it, vi } from 'vitest'
import defaultBackground from '@/assets/images/default_bg.webp'
import GameBackground from '../GameBackground.vue'

const mocks = vi.hoisted(() => ({
  uiStore: {
    currentBackground: '@/assets/images/default_bg.webp',
    currentBackgroundTransition: 300,
    currentBackgroundEffect: 'None',
    currentSoundEffect: null as string | null,
    currentBackgroundMusic: 'None',
    backgroundVolume: 50,
    bgMusicPaused: false,
    bgMusicStoped: false,
    bgMusicMode: 'loop-single',
    handleBackgroundMusicEnd: vi.fn(),
  },
}))

vi.mock('@/stores/modules/ui/ui', () => ({
  useUIStore: () => mocks.uiStore,
}))

function mountGameBackground() {
  return mount(GameBackground, {
    global: {
      stubs: {
        ImageAcrossFade: {
          props: ['src'],
          template: '<img data-testid="background-image" :src="src" />',
        },
        AudioAcrossFade: true,
        StarField: true,
        Rain: true,
        Sakura: true,
        Snow: true,
        Fireworks: true,
      },
    },
  })
}

describe('GameBackground', () => {
  it('resolves the default asset alias to the bundled image URL', () => {
    mocks.uiStore.currentBackground = '@/assets/images/default_bg.webp'
    const wrapper = mountGameBackground()

    expect(wrapper.get('[data-testid="background-image"]').attributes('src')).toBe(defaultBackground)
  })

  it('keeps a selected custom background URL', () => {
    mocks.uiStore.currentBackground = 'http://localhost:8765/assets/custom.webp'
    const wrapper = mountGameBackground()

    expect(wrapper.get('[data-testid="background-image"]').attributes('src')).toBe(
      'http://localhost:8765/assets/custom.webp',
    )
  })
})
