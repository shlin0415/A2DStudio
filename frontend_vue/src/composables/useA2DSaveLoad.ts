import { useScriptStore, type ScriptSnapshot } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import type { GameSnapshot } from '@/stores/modules/game/state'

/** Single source of truth for the snapshot format version this build can read. */
export const SNAPSHOT_VERSION = 1

/** Phases during which import is permitted (backend is not actively pushing). */
const IMPORTABLE_PHASES = new Set(['idle', 'paused'])

export interface ExportEnvelope {
  version: number
  exportedAt: string
  script: ScriptSnapshot
  game: GameSnapshot
}

export interface ImportResult {
  ok: boolean
  error?: string
}

function triggerDownload(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  document.body.appendChild(a)
  a.click()
  document.body.removeChild(a)
  URL.revokeObjectURL(url)
}

function stamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}${p(d.getMonth() + 1)}${p(d.getDate())}-${p(d.getHours())}${p(d.getMinutes())}${p(d.getSeconds())}`
}

/**
 * Build a snapshot of the current script + game stores and download it as `<timestamp>.a2d.json`.
 */
export function exportSession() {
  const script = useScriptStore()
  const game = useGameStore()

  const envelope: ExportEnvelope = {
    version: SNAPSHOT_VERSION,
    exportedAt: new Date().toISOString(),
    script: {
      version: SNAPSHOT_VERSION,
      exportedAt: new Date().toISOString(),
      lines: script.lines,
      phase: script.phase,
      selectedLineId: script.selectedLineId,
      playingLineId: script.playingLineId,
      editedText: script.editedText,
      activeTab: script.activeTab,
    },
    game: {
      gameRoles: game.gameRoles,
      presentRoleIds: game.presentRoleIds,
    },
  }

  const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: 'application/json' })
  triggerDownload(blob, `save-${stamp()}.a2d.json`)
}

/** Is this a minimally-plausible ScriptLine (must have the fields the UI reads)? */
function isScriptLine(v: unknown): v is { id: string; speaker: string; display_text: string; tts_text: string; index: number } {
  if (typeof v !== 'object' || v === null) return false
  const o = v as Record<string, unknown>
  return typeof o.id === 'string' && typeof o.speaker === 'string'
    && typeof o.display_text === 'string' && typeof o.tts_text === 'string'
    && typeof o.index === 'number'
}

/** Minimal structural validation — guards against garbage input before we touch the store. */
export function validateEnvelope(raw: unknown): ImportResult {
  if (typeof raw !== 'object' || raw === null) {
    return { ok: false, error: '文件不是有效的 JSON 对象' }
  }
  const env = raw as Record<string, unknown>
  if (typeof env.version !== 'number' || !Number.isFinite(env.version)) {
    return { ok: false, error: '缺少 version 字段' }
  }
  if (env.version > SNAPSHOT_VERSION) {
    return { ok: false, error: `不支持的版本: v${env.version}（当前支持 v${SNAPSHOT_VERSION}）` }
  }
  if (env.version < 1) {
    return { ok: false, error: `无效的版本号: ${env.version}` }
  }
  const script = (env as unknown as ExportEnvelope).script
  if (!script || !Array.isArray(script.lines)) {
    return { ok: false, error: 'script.lines 缺失或格式错误' }
  }
  // Every line must carry the fields the UI reads — otherwise import crashes downstream.
  for (let i = 0; i < script.lines.length; i++) {
    if (!isScriptLine(script.lines[i])) {
      return { ok: false, error: `第 ${i + 1} 行结构不完整（缺 id/speaker/display_text/tts_text/index）` }
    }
  }
  return { ok: true }
}

/**
 * Read + validate a File, then import it into the stores.
 *
 * Semantics (DEC-1 = preview mode):
 *  - Full overwrite: reset() first, then fill from snapshot.
 *  - Phase-gated: only allowed in idle/paused phases.
 *  - On success, phase is forced to `paused` so the user must explicitly continue.
 *  - On failure, stores are left untouched.
 */
export async function importSession(file: File): Promise<ImportResult> {
  const script = useScriptStore()

  if (!IMPORTABLE_PHASES.has(script.phase)) {
    return { ok: false, error: '请先暂停当前生成再导入' }
  }

  let text: string
  try {
    text = await file.text()
  } catch {
    return { ok: false, error: '文件读取失败' }
  }

  let raw: unknown
  try {
    raw = JSON.parse(text)
  } catch {
    return { ok: false, error: 'JSON 解析失败：文件已损坏' }
  }

  const check = validateEnvelope(raw)
  if (!check.ok) return check

  const env = raw as unknown as ExportEnvelope

  // --- Full overwrite: wipe script store, then fill both stores from snapshot ---
  script.reset()
  // importFromSnapshot forces phase=poused internally; pass through.
  script.importFromSnapshot(env.script)
  // game store import handles mainRoleId reset + presentRoleIds cross-check internally.
  useGameStore().importFromSnapshot({
    gameRoles: env.game?.gameRoles ?? {},
    presentRoleIds: env.game?.presentRoleIds ?? [],
  })

  // Force paused: user must explicitly continue (preview-mode semantics).
  script.setPhase('paused')

  return { ok: true }
}
