import { useScriptStore, type ScriptSnapshot } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import type { GameSnapshot } from '@/stores/modules/game/state'

/** Single source of truth for the snapshot format version this build can read. */
export const SNAPSHOT_VERSION = 2

/** All historically-supported versions (for backward-compatible import). */
const SUPPORTED_VERSIONS = new Set([1, 2])

/** Phases during which import is permitted (backend is not actively pushing). */
const IMPORTABLE_PHASES = new Set(['idle', 'paused'])

/** sessionStorage key holding the pre-import rollback snapshot (preview-mode, DEC-1). */
const ROLLBACK_KEY = 'a2d_import_rollback'

interface RollbackData {
  script: ScriptSnapshot
  game: GameSnapshot
  ts: number
}

export interface StageInfo {
  id: string
  default_background: string
}

export interface ExportEnvelope {
  version: number
  exportedAt: string
  script: ScriptSnapshot
  game: GameSnapshot
  stages?: StageInfo[]
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
    // stages[] carries stage_id -> default_background for replay background resolution.
    stages: Object.entries(script.stageMap).map(([id, default_background]) => ({ id, default_background })),
  }

  // Option B persistence: send envelope to backend to copy WAVs into a
  // per-save audio dir + rewrite audio_paths to the persistent route.
  // Falls back to plain client download if the backend is unavailable.
  persistToBackend(envelope).catch(() => { /* offline fallback below */ })

  const blob = new Blob([JSON.stringify(envelope, null, 2)], { type: 'application/json' })
  triggerDownload(blob, `save-${stamp()}.a2d.json`)
}

/** POST envelope to backend for persistent storage. Best-effort (no throw). */
async function persistToBackend(envelope: ExportEnvelope): Promise<void> {
  const res = await fetch('/api/a2d/save', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ envelope }),
  })
  if (!res.ok) throw new Error(`backend save failed: ${res.status}`)
  const data = await res.json()
  if (data?.save_id) {
    console.log(`[A2D] save persisted: ${data.save_id}`)
  }
}

/**
 * Is this a minimally-plausible ScriptLine (must have the fields the UI reads)?
 * audio_path / overlay / stage_id are OPTIONAL (v1 saves lack them) — replay
 * degrades gracefully to null when absent. Only the core UI fields are required.
 */
function isScriptLine(v: unknown): v is { id: string; speaker: string; display_text: string; tts_text: string; index: number } {
  if (typeof v !== 'object' || v === null) return false
  const o = v as Record<string, unknown>
  // audio_path is optional (v1 saves lack it) — but if present, MUST be string.
  if (o.audio_path != null && typeof o.audio_path !== 'string') return false
  return typeof o.id === 'string' && typeof o.speaker === 'string'
    && typeof o.display_text === 'string' && typeof o.tts_text === 'string'
    && typeof o.index === 'number'
}

/** Validate a single image_overlay entry has all required fields. */
function isValidImageOverlay(v: unknown): boolean {
  if (typeof v !== 'object' || v === null) return false
  const o = v as Record<string, unknown>
  return typeof o.path === 'string' && typeof o.x === 'number' && typeof o.y === 'number'
    && typeof o.w === 'number' && typeof o.h === 'number'
    && typeof o.opacity === 'number' && typeof o.z === 'number'
}

/** Validate overlay shape — guards against malformed overlay objects. */
function validateOverlayShape(overlay: unknown): boolean {
  if (overlay == null) return true // optional
  if (typeof overlay !== 'object') return false
  const o = overlay as Record<string, unknown>
  if (o.background != null && typeof o.background !== 'string') return false
  if (o.bgm != null && typeof o.bgm !== 'string') return false
  if (Array.isArray(o.image_overlays)) {
    for (let i = 0; i < o.image_overlays.length; i++) {
      if (!isValidImageOverlay(o.image_overlays[i])) return false
    }
  }
  return true
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
  if (env.version < 1) {
    return { ok: false, error: `无效的版本号: ${env.version}` }
  }
  if (!SUPPORTED_VERSIONS.has(env.version)) {
    return { ok: false, error: `不支持的版本: v${env.version}（当前支持 v${[...SUPPORTED_VERSIONS].sort().join('/')}）` }
  }
  const script = (env as unknown as ExportEnvelope).script
  if (!script || !Array.isArray(script.lines)) {
    return { ok: false, error: 'script.lines 缺失或格式错误' }
  }
  // Every line must carry the fields the UI reads — otherwise import crashes downstream.
  for (let i = 0; i < script.lines.length; i++) {
    const line = script.lines[i] as unknown as Record<string, unknown>
    if (!isScriptLine(script.lines[i])) {
      return { ok: false, error: `第 ${i + 1} 行结构不完整（缺 id/speaker/display_text/tts_text/index）` }
    }
    // Overlay (if present) must have valid shape — malformed overlay crashes replay render.
    if (!validateOverlayShape(line.overlay)) {
      return { ok: false, error: `第 ${i + 1} 行 overlay 格式非法` }
    }
  }
  return { ok: true }
}

/**
 * Capture the current store state into sessionStorage as the rollback point.
 * Call BEFORE reset(). On refresh, `initImportRollback()` restores this state,
 * cancelling the import (preview-mode semantics per DEC-1).
 */
export function captureRollback(): void {
  const script = useScriptStore()
  const game = useGameStore()
  const data: RollbackData = {
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
    ts: Date.now(),
  }
  try {
    sessionStorage.setItem(ROLLBACK_KEY, JSON.stringify(data))
  } catch {
    // sessionStorage full or blocked — import proceeds without rollback safety.
  }
}

/**
 * Restore the pre-import state from sessionStorage. Returns true if a rollback
 * was applied. Safe to call on every app boot: no-op when key is absent or corrupt.
 */
export function rollbackImport(): boolean {
  const raw = sessionStorage.getItem(ROLLBACK_KEY)
  if (!raw) return false
  sessionStorage.removeItem(ROLLBACK_KEY)
  let data: RollbackData
  try {
    data = JSON.parse(raw) as RollbackData
  } catch {
    return false
  }
  const script = useScriptStore()
  script.reset()
  script.importFromSnapshot(data.script)
  useGameStore().importFromSnapshot(data.game)
  return true
}

/** Commit the current import: clear the rollback key so refresh keeps imported state. */
export function commitImport(): void {
  sessionStorage.removeItem(ROLLBACK_KEY)
}

/**
 * Boot hook — call once at app startup (before WS traffic). Restores pre-import
 * state if the user imported then refreshed without explicitly continuing.
 */
export function initImportRollback(): void {
  rollbackImport()
}

/**
 * Read + validate a File, then import it into the stores.
 *
 * Semantics (DEC-1 = preview mode):
 *  - Capture rollback point, then full overwrite (reset → fill from snapshot).
 *  - Phase-gated: only allowed in idle/paused phases.
 *  - On success, phase is forced to `paused` (inside importFromSnapshot) so the
 *    user must explicitly continue.
 *  - On failure, stores are left untouched (and rollback key is not written).
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

  // --- Preview mode: capture rollback point BEFORE wiping ---
  captureRollback()

  // --- Full overwrite: wipe script store, then fill both stores from snapshot ---
  script.reset()
  // importFromSnapshot forces phase=paused internally; that is the contract.
  script.importFromSnapshot(env.script)
  // game store import handles mainRoleId reset + presentRoleIds cross-check internally.
  useGameStore().importFromSnapshot({
    gameRoles: env.game?.gameRoles ?? {},
    presentRoleIds: env.game?.presentRoleIds ?? [],
  })
  // P1 replay: populate stageMap from envelope stages[] (optional, v2 field).
  if (env.stages?.length) {
    script.setStageMap(Object.fromEntries(env.stages.map(s => [s.id, s.default_background])))
  }

  return { ok: true }
}
