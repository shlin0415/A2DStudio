import { emitTrace } from '@/utils/a2d-trace'

export type StageActionKind = 'animation' | 'bubble'
export type StageActionOutcome = 'completed' | 'cancelled'

export interface StageAction {
  actionId: string
  kind: StageActionKind
  lineId: string | null
  roleId: number
}

let actionSequence = 0
const pendingActionIds = new Map<string, Set<string>>()
const actionWaiters = new Map<string, Set<() => void>>()

export function beginStageAction(kind: StageActionKind, lineId: string | null, roleId: number): StageAction {
  const action: StageAction = {
    actionId: `stage-action-${++actionSequence}`,
    kind,
    lineId,
    roleId,
  }
  if (lineId) {
    const pending = pendingActionIds.get(lineId) ?? new Set<string>()
    pending.add(action.actionId)
    pendingActionIds.set(lineId, pending)
  }
  emitTrace('stage_action_start', {
    actionId: action.actionId,
    kind,
    ...(lineId ? { lineId } : {}),
    roleId,
  })
  return action
}

export function endStageAction(action: StageAction, outcome: StageActionOutcome): void {
  emitTrace('stage_action_end', {
    actionId: action.actionId,
    kind: action.kind,
    ...(action.lineId ? { lineId: action.lineId } : {}),
    roleId: action.roleId,
    outcome,
  })

  if (!action.lineId) return
  const pending = pendingActionIds.get(action.lineId)
  if (!pending?.delete(action.actionId) || pending.size > 0) return

  pendingActionIds.delete(action.lineId)
  const waiters = actionWaiters.get(action.lineId)
  if (!waiters) return
  actionWaiters.delete(action.lineId)
  for (const resolve of waiters) resolve()
}

export function waitForStageActions(lineId: string): Promise<void> {
  const pending = pendingActionIds.get(lineId)
  if (!pending || pending.size === 0) return Promise.resolve()

  emitTrace('stage_action_wait', { lineId, pendingCount: pending.size })
  return new Promise((resolve) => {
    const waiters = actionWaiters.get(lineId) ?? new Set<() => void>()
    waiters.add(resolve)
    actionWaiters.set(lineId, waiters)
  })
}

/** Reset singleton coordination state between unit tests. */
export function _resetStageActions(): void {
  for (const waiters of actionWaiters.values()) {
    for (const resolve of waiters) resolve()
  }
  actionWaiters.clear()
  pendingActionIds.clear()
  actionSequence = 0
}
