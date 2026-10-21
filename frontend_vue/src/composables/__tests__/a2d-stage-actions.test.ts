import { beforeEach, describe, expect, it, vi } from 'vitest'
import {
  _resetStageActions,
  beginStageAction,
  endStageAction,
  waitForStageActions,
} from '../a2d-stage-actions'

const emitTrace = vi.hoisted(() => vi.fn())

vi.mock('@/utils/a2d-trace', () => ({ emitTrace }))

describe('A2D stage action completion barrier', () => {
  beforeEach(() => {
    _resetStageActions()
    emitTrace.mockClear()
  })

  it('resolves only after every action attached to the same line ends', async () => {
    const animation = beginStageAction('animation', 'line-1', 1)
    const bubble = beginStageAction('bubble', 'line-1', 1)
    let isResolved = false
    const wait = waitForStageActions('line-1').then(() => { isResolved = true })

    await Promise.resolve()
    expect(isResolved).toBe(false)

    endStageAction(animation, 'completed')
    await Promise.resolve()
    expect(isResolved).toBe(false)

    endStageAction(bubble, 'completed')
    await wait
    expect(isResolved).toBe(true)
  })

  it('does not block a different line and records metadata without dialogue', async () => {
    const action = beginStageAction('bubble', 'line-1', 1)

    await expect(waitForStageActions('line-2')).resolves.toBeUndefined()

    expect(emitTrace).toHaveBeenCalledWith('stage_action_start', expect.objectContaining({
      kind: 'bubble',
      lineId: 'line-1',
      roleId: 1,
    }))
    expect(JSON.stringify(emitTrace.mock.calls)).not.toContain('台词')
    endStageAction(action, 'cancelled')
  })
})
