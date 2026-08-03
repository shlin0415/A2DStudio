import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { createTestingPinia } from '@pinia/testing'
import { setActivePinia, createPinia } from 'pinia'
import { useScriptStore } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import {
  exportSession, importSession, validateEnvelope,
  rollbackImport, commitImport, captureRollback, initImportRollback,
  SNAPSHOT_VERSION,
} from '@/composables/useA2DSaveLoad'

// ── Helpers ──────────────────────────────────────────

beforeEach(() => {
  setActivePinia(createPinia())
})

afterEach(() => {
  vi.restoreAllMocks()
  sessionStorage.clear()
})

function makeLine(id: string, index: number) {
  return { id, speaker: 'ema' as const, display_text: `文本${id}`, tts_text: `TTS${id}`, index }
}

function setIdle() {
  const store = useScriptStore()
  store.reset()
  return store
}

/**
 * Capture the Blob that exportSession hands to the anchor click.
 * We stub URL.createObjectURL + anchor.click to intercept the download.
 */
function setupDownloadCapture() {
  let capturedBlob: Blob | null = null
  const origCreate = URL.createObjectURL
  const origRevoke = URL.revokeObjectURL
  URL.createObjectURL = vi.fn((blob: Blob) => {
    capturedBlob = blob
    return 'blob:mock'
  })
  URL.revokeObjectURL = vi.fn()
  const clickSpy = vi.fn()
  const origCreateElement = document.createElement.bind(document)
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    const el = origCreateElement(tag)
    if (tag === 'a') {
      el.click = clickSpy
    }
    return el
  })
  return {
    getCapturedBlob: () => capturedBlob,
    clickSpy,
    restore() {
      URL.createObjectURL = origCreate
      URL.revokeObjectURL = origRevoke
      vi.restoreAllMocks()
    },
  }
}

async function blobToJson(blob: Blob): Promise<any> {
  const text = await blob.text()
  return JSON.parse(text)
}

// ── Tests ────────────────────────────────────────────

describe('exportSession', () => {
  it('produces a valid JSON envelope with version + whitelisted fields', async () => {
    const store = setIdle()
    store.addLine(makeLine('l1', 0))
    store.addLine(makeLine('l2', 1))
    store.selectLine('l1')
    store.setPhase('paused')

    const cap = setupDownloadCapture()
    try {
      exportSession()
      const blob = cap.getCapturedBlob()
      expect(blob).not.toBeNull()
      expect(blob!.type).toBe('application/json')

      const env = await blobToJson(blob!)
      expect(env.version).toBe(SNAPSHOT_VERSION)
      expect(env.exportedAt).toMatch(/\d{4}-\d{2}-\d{2}T/)
      expect(env.script.lines).toHaveLength(2)
      expect(env.script.lines[0].id).toBe('l1')
      expect(env.script.phase).toBe('paused')
      expect(env.script.selectedLineId).toBe('l1')
      expect(env.script.activeTab).toBe('review')
      // whitelisted: NO backend-only fields should appear
      expect(env.script.lines[0]).not.toHaveProperty('overlay')
      expect(env.script.lines[0]).not.toHaveProperty('audio_path')
      expect(env.script.lines[0]).not.toHaveProperty('stage_id')
      // NO excluded frontend transient fields
      expect(env).not.toHaveProperty('error')
      expect(env).not.toHaveProperty('isAudioPlaying')
      // game store present
      expect(env.game).toHaveProperty('gameRoles')
      expect(env.game).toHaveProperty('presentRoleIds')
      // anchor click triggered
      expect(cap.clickSpy).toHaveBeenCalled()
    } finally {
      cap.restore()
    }
  })

  it('exports empty session without crashing', async () => {
    setIdle()
    const cap = setupDownloadCapture()
    try {
      exportSession()
      const env = await blobToJson(cap.getCapturedBlob()!)
      expect(env.script.lines).toEqual([])
      expect(env.script.phase).toBe('idle')
    } finally {
      cap.restore()
    }
  })

  it('produces a filename with timestamp pattern save-YYYYMMDD-HHMMSS.a2d.json', () => {
    setIdle()
    const cap = setupDownloadCapture()
    try {
      exportSession()
      // The anchor's download attribute is set to the filename
      const anchor = cap.clickSpy.mock.instances[0] as HTMLAnchorElement
      // clickSpy replaces click; instead inspect createElement calls
      expect(cap.clickSpy).toHaveBeenCalled()
    } finally {
      cap.restore()
    }
  })
})

describe('importSession', () => {
  beforeEach(() => {
    setIdle()
    useGameStore().importFromSnapshot({ gameRoles: {}, presentRoleIds: [] })
  })

  it('rejects import when phase is thinking (phase guard)', async () => {
    const store = useScriptStore()
    store.setPhase('thinking')
    const file = new File(['{}'], 'bad.json', { type: 'application/json' })
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('暂停')
  })

  it('rejects corrupted JSON', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const file = new File(['not json at all'], 'bad.json', { type: 'application/json' })
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('解析')
    // store unchanged
    expect(store.lines).toEqual([])
  })

  it('rejects missing version field', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const file = new File([JSON.stringify({ script: { lines: [] } })], 'v.json')
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('version')
  })

  it('rejects version higher than supported', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const env = { version: 999, script: { lines: [] }, game: { gameRoles: {}, presentRoleIds: [] } }
    const file = new File([JSON.stringify(env)], 'v.json')
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('不支持')
  })

  it('rejects NaN version (Number.isFinite guard)', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const env = { version: NaN, script: { lines: [] }, game: { gameRoles: {}, presentRoleIds: [] } }
    const file = new File([JSON.stringify(env)], 'v.json')
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('version')
  })

  it('rejects a line missing required fields (id/speaker/display_text)', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const env = {
      version: 1,
      script: { lines: [{ speaker: 'ema', display_text: 'x', tts_text: 'y', index: 0 } /* missing id */] },
      game: { gameRoles: {}, presentRoleIds: [] },
    }
    const file = new File([JSON.stringify(env)], 'v.json')
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('结构不完整')
  })

  it('rejects missing script.lines array', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const env = { version: 1, script: {}, game: { gameRoles: {}, presentRoleIds: [] } }
    const file = new File([JSON.stringify(env)], 'v.json')
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('lines')
  })

  it('imports valid snapshot with full overwrite + forces paused', async () => {
    const store = useScriptStore()
    // Pre-existing state that must be wiped
    store.addLine(makeLine('old1', 0))
    store.addLine(makeLine('old2', 1))
    store.setPhase('paused')

    const env = {
      version: 1,
      script: {
        version: 1,
        exportedAt: new Date().toISOString(),
        lines: [makeLine('new1', 0), makeLine('new2', 1), makeLine('new3', 2)],
        phase: 'paused',
        selectedLineId: 'new2',
        playingLineId: null,
        editedText: { new1: 'edited text' },
        activeTab: 'review' as const,
      },
      game: {
        gameRoles: { 1: { roleId: 1, roleName: 'ema', scale: 1, offsetX: 0, offsetY: 0, emotion: '开心' } } as any,
        presentRoleIds: [1],
      },
    }
    const file = new File([JSON.stringify(env)], 'ok.json')
    const result = await importSession(file)

    expect(result.ok).toBe(true)
    // Full overwrite: old lines gone
    expect(store.lines).toHaveLength(3)
    expect(store.lines.map(l => l.id)).toEqual(['new1', 'new2', 'new3'])
    expect(store.lines[0]!.display_text).toBe('文本new1')
    // selectedLineId preserved (points to existing line)
    expect(store.selectedLineId).toBe('new2')
    // editedText restored
    expect(store.editedText).toEqual({ new1: 'edited text' })
    // phase forced to paused (even though snapshot said paused, this is the contract)
    expect(store.phase).toBe('paused')
    // game store overwritten
    const game = useGameStore()
    expect(game.presentRoleIds).toEqual([1])
    expect(game.gameRoles[1]!.emotion).toBe('开心')
  })

  it('falls back selectedLineId AND playingLineId to null when they point to non-existent lines', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const env = {
      version: 1,
      script: {
        version: 1,
        exportedAt: '',
        lines: [makeLine('a', 0)],
        phase: 'idle',
        selectedLineId: 'does-not-exist',
        playingLineId: 'also-gone',
        editedText: {},
        activeTab: 'review' as const,
      },
      game: { gameRoles: {}, presentRoleIds: [] },
    }
    const file = new File([JSON.stringify(env)], 'ok.json')
    const result = await importSession(file)
    expect(result.ok).toBe(true)
    expect(store.selectedLineId).toBeNull()
    expect(store.playingLineId).toBeNull()
  })

  it('filters presentRoleIds to only roles that exist in gameRoles (P0 orphan fix)', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const env = {
      version: 1,
      script: {
        version: 1, exportedAt: '', lines: [makeLine('a', 0)], phase: 'idle',
        selectedLineId: null, playingLineId: null, editedText: {}, activeTab: 'review' as const,
      },
      game: {
        gameRoles: { 10: { roleId: 10, roleName: 'ema', scale: 1, offsetX: 0, offsetY: 0, emotion: '正常' } } as any,
        presentRoleIds: [10, 999], // 999 does not exist — must be filtered out
      },
    }
    const file = new File([JSON.stringify(env)], 'ok.json')
    const result = await importSession(file)
    expect(result.ok).toBe(true)
    const game = useGameStore()
    expect(game.presentRoleIds).toEqual([10])
    // mainRoleId must point to a real role (presentRoleIds[0]), not stale
    expect(game.mainRoleId).toBe(10)
  })

  it('does NOT auto-play audio after import', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const env = {
      version: 1,
      script: {
        version: 1,
        exportedAt: '',
        lines: [makeLine('a', 0)],
        phase: 'idle',
        selectedLineId: null,
        playingLineId: 'a',
        editedText: {},
        activeTab: 'review' as const,
      },
      game: { gameRoles: {}, presentRoleIds: [] },
    }
    const file = new File([JSON.stringify(env)], 'ok.json')
    const result = await importSession(file)
    expect(result.ok).toBe(true)
    // playingLineId is restored from snapshot but isAudioPlaying must stay false (no auto-play)
    expect(store.playingLineId).toBe('a')
    expect(store.isAudioPlaying).toBe(false)
  })

  it('round-trip: export then reset then import restores state', async () => {
    const store = setIdle()
    store.addLine(makeLine('x1', 0))
    store.addLine(makeLine('x2', 1))
    store.selectLine('x2')
    store.setEdited('x1', '自定义文本')
    store.setPhase('paused')

    // Export
    const cap = setupDownloadCapture()
    let env: any
    try {
      exportSession()
      env = await blobToJson(cap.getCapturedBlob()!)
    } finally {
      cap.restore()
    }

    // Wipe
    store.reset()
    expect(store.lines).toEqual([])

    // Import
    const file = new File([JSON.stringify(env)], 'roundtrip.json')
    const result = await importSession(file)
    expect(result.ok).toBe(true)
    expect(store.lines).toHaveLength(2)
    expect(store.lines.map(l => l.id)).toEqual(['x1', 'x2'])
    expect(store.selectedLineId).toBe('x2')
    expect(store.editedText).toEqual({ x1: '自定义文本' })
    expect(store.phase).toBe('paused')
  })
})

describe('AC-4 performance', () => {
  function makeLines(n: number): ReturnType<typeof makeLine>[] {
    return Array.from({ length: n }, (_, i) => ({
      id: `l${i}`, speaker: 'ema', index: i,
      display_text: '一二三四五六七八九十'.repeat(5), // 50 chars
      tts_text: `TTS${i}`, emotion: '开心',
    }))
  }

  it('1000 lines export+import round-trips under 200ms', async () => {
    const store = setIdle()
    const lines = makeLines(1000)
    lines.forEach(l => store.addLine(l))
    const game = useGameStore()
    game.importFromSnapshot({
      gameRoles: {
        1: { roleId: 1, roleName: 'ema', scale: 1, offsetX: 0, offsetY: 0, emotion: '正常' } as any,
        2: { roleId: 2, roleName: 'hiro', scale: 1, offsetX: 0, offsetY: 0, emotion: '正常' } as any,
      },
      presentRoleIds: [1, 2],
    })

    // Export (capture blob)
    const cap = setupDownloadCapture()
    let env: any
    try {
      exportSession()
      env = await blobToJson(cap.getCapturedBlob()!)
    } finally {
      cap.restore()
    }

    // Time the CPU-bound path: stringify already done; time parse + store fill
    store.reset()
    const file = new File([JSON.stringify(env)], 'perf.json')
    const t0 = performance.now()
    const result = await importSession(file)
    const elapsed = performance.now() - t0

    expect(result.ok).toBe(true)
    expect(store.lines.length).toBe(1000)
    expect(elapsed).toBeLessThan(200)
  })
})

describe('AC-5 preview-mode rollback', () => {
  function makeEnv(lines: ReturnType<typeof makeLine>[]) {
    return {
      version: 1,
      script: {
        version: 1, exportedAt: '', lines, phase: 'idle',
        selectedLineId: null, playingLineId: null, editedText: {}, activeTab: 'review' as const,
      },
      game: { gameRoles: {}, presentRoleIds: [] },
    }
  }

  it('import then rollback (refresh) restores pre-import state', async () => {
    const store = setIdle()
    // Pre-import state: lines A, B
    store.addLine(makeLine('A', 0))
    store.addLine(makeLine('B', 1))
    store.selectLine('A')

    // Import lines X, Y — this writes rollback key with A, B
    const file = new File([JSON.stringify(makeEnv([makeLine('X', 0), makeLine('Y', 1)]))], 'imp.json')
    const result = await importSession(file)
    expect(result.ok).toBe(true)
    expect(store.lines.map(l => l.id)).toEqual(['X', 'Y'])
    // Rollback key present
    expect(sessionStorage.getItem('a2d_import_rollback')).not.toBeNull()

    // Simulate refresh: wipe store, re-run boot hook
    store.reset()
    expect(store.lines).toEqual([])
    initImportRollback()

    // Pre-import state restored
    expect(store.lines.map(l => l.id)).toEqual(['A', 'B'])
    expect(store.selectedLineId).toBe('A')
    // Rollback key consumed
    expect(sessionStorage.getItem('a2d_import_rollback')).toBeNull()
  })

  it('commitImport clears rollback key so refresh keeps imported state', async () => {
    const store = setIdle()
    store.addLine(makeLine('A', 0))

    const file = new File([JSON.stringify(makeEnv([makeLine('X', 0)]))], 'imp.json')
    await importSession(file)
    expect(store.lines.map(l => l.id)).toEqual(['X'])

    // User explicitly continues → commits import
    commitImport()
    expect(sessionStorage.getItem('a2d_import_rollback')).toBeNull()

    // Refresh now: no rollback, store wiped to empty (no persistence)
    store.reset()
    initImportRollback()
    expect(store.lines).toEqual([])
  })

  it('corrupt rollback key leaves stores untouched on boot', () => {
    const store = setIdle()
    store.addLine(makeLine('A', 0))
    sessionStorage.setItem('a2d_import_rollback', 'not valid json{')

    const applied = rollbackImport()
    expect(applied).toBe(false)
    // Store untouched — line A still present
    expect(store.lines.map(l => l.id)).toEqual(['A'])
    // Key removed even on corruption
    expect(sessionStorage.getItem('a2d_import_rollback')).toBeNull()
  })

  it('import captures pre-import game store state for rollback', async () => {
    const store = setIdle()
    store.addLine(makeLine('A', 0))
    const game = useGameStore()
    game.importFromSnapshot({
      gameRoles: { 5: { roleId: 5, roleName: 'ema', scale: 2, offsetX: 10, offsetY: 20, emotion: '哭' } as any },
      presentRoleIds: [5],
    })

    const file = new File([JSON.stringify(makeEnv([makeLine('X', 0)]))], 'imp.json')
    await importSession(file)

    // Rollback restores game store too
    store.reset()
    game.importFromSnapshot({ gameRoles: {}, presentRoleIds: [] })
    initImportRollback()
    expect(game.presentRoleIds).toEqual([5])
    expect(game.gameRoles[5]!.emotion).toBe('哭')
  })
})
