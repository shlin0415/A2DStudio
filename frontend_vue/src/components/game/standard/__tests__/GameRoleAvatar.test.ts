import { flushPromises, mount } from '@vue/test-utils'
import { reactive } from 'vue'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import GameRoleAvatar from '../GameRoleAvatar.vue'
import { getProjectAvatarRegistryKey, registerImportedProjectAssets } from '@/composables/a2d-project-runtime-assets'

const mocks = vi.hoisted(() => ({
  emitTrace: vi.fn(),
  gameStore: { command: null as string | null, presentRoleIds: [1] },
  scriptStore: { playingLineId: 'line-7' as string | null },
}))

vi.mock('@/utils/a2d-trace', () => ({ emitTrace: mocks.emitTrace }))
vi.mock('@/stores/modules/game', () => ({ useGameStore: () => mocks.gameStore }))
vi.mock('@/stores/modules/script', () => ({ useScriptStore: () => mocks.scriptStore }))
vi.mock('@/controllers/emotion/config', () => ({
  EMOTION_CONFIG_EMO: { 正常: '正常', 高兴: '高兴' },
  EMOTION_CONFIG: {
    正常: { animation: 'none', bubbleImage: 'none', bubbleClass: 'none', audio: 'none' },
    高兴: { animation: 'happy-bounce', bubbleImage: 'happy.webp', bubbleClass: 'happy', audio: 'none' },
  },
}))

function makeRole() {
  return reactive({
    roleId: 1,
    scriptRoleKey: undefined as string | undefined,
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
    clothesName: '默认',
    bodyPart: {},
    character_folder: 'ema',
  })
}

function mountAvatar(role: ReturnType<typeof makeRole>) {
  return mount(GameRoleAvatar, {
    props: { role },
    global: {
      stubs: {
        TouchAreas: true,
        ImageAcrossFade: {
          props: ['src'],
          template: '<div data-testid="avatar-image" :data-src="src" />',
          methods: { waitForLoad: () => Promise.resolve() },
        },
      },
    },
  })
}

describe('GameRoleAvatar stage action trace', () => {
  beforeEach(() => {
    mocks.emitTrace.mockClear()
    mocks.scriptStore.playingLineId = 'line-7'
    vi.useRealTimers()
  })

  it('records animation and bubble start/end with metadata only', async () => {
    const role = makeRole()
    const wrapper = mountAvatar(role)
    await flushPromises()
    mocks.emitTrace.mockClear()

    vi.useFakeTimers()
    role.emotion = '高兴'
    await flushPromises()

    expect(mocks.emitTrace).toHaveBeenCalledWith('stage_action_start', expect.objectContaining({
      actionId: expect.any(String),
      kind: 'animation',
      lineId: 'line-7',
      roleId: 1,
    }))
    expect(mocks.emitTrace).toHaveBeenCalledWith('stage_action_start', expect.objectContaining({
      kind: 'bubble',
      lineId: 'line-7',
      roleId: 1,
    }))
    expect(JSON.stringify(mocks.emitTrace.mock.calls)).not.toContain('happy.webp')
    expect(JSON.stringify(mocks.emitTrace.mock.calls)).not.toContain('高兴')

    await wrapper.get('.happy-bounce').trigger('animationend', { animationName: 'happyBounce' })
    expect(mocks.emitTrace).toHaveBeenCalledWith('stage_action_end', expect.objectContaining({
      kind: 'animation',
      lineId: 'line-7',
      outcome: 'completed',
    }))

    await vi.advanceTimersByTimeAsync(2000)
    const transitionEnd = new Event('transitionend', { bubbles: true })
    Object.defineProperty(transitionEnd, 'propertyName', { value: 'opacity' })
    wrapper.get('.bubble').element.dispatchEvent(transitionEnd)
    expect(mocks.emitTrace).toHaveBeenCalledWith('stage_action_end', expect.objectContaining({
      kind: 'bubble',
      lineId: 'line-7',
      outcome: 'completed',
    }))
    vi.useRealTimers()
    wrapper.unmount()
  })

  it('uses the packaged avatar URL for an imported project role', async () => {
    const role = makeRole()
    role.scriptRoleKey = 'ema'
    const avatarUrl = 'blob:project-avatar'
    const avatarKey = getProjectAvatarRegistryKey('ema', 'default', '正常')
    registerImportedProjectAssets(new Map([[avatarKey, avatarUrl]]), [])

    const wrapper = mountAvatar(role)
    await flushPromises()

    expect(wrapper.get('[data-testid="avatar-image"]').attributes('data-src')).toBe(avatarUrl)
    expect(wrapper.get('[data-testid="avatar-image"]').attributes('data-src')).not.toContain('/api/v1/chat/character/get_avatar/')
    wrapper.unmount()
    registerImportedProjectAssets(new Map(), [])
  })
})
