import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { setActivePinia, createPinia } from 'pinia'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
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

function makeLine(id: string, index: number, extra: Partial<ScriptLine> = {}) {
  return { id, speaker: 'ema' as const, display_text: `文本${id}`, tts_text: `TTS${id}`, index, audio_path: null, overlay: null, stage_id: '', ...extra }
}

function setIdle() {
  const store = useScriptStore()
  store.reset()
  return store
}

/** Build the same snapshot shape `exportSession` produces (without Blob/download). */
function buildSnapshot(store: ReturnType<typeof useScriptStore>, game: ReturnType<typeof useGameStore>) {
  return {
    version: SNAPSHOT_VERSION,
    exportedAt: new Date().toISOString(),
    script: {
      version: SNAPSHOT_VERSION,
      exportedAt: new Date().toISOString(),
      lines: store.lines,
      phase: store.phase,
      selectedLineId: store.selectedLineId,
      playingLineId: store.playingLineId,
      editedText: store.editedText,
      activeTab: store.activeTab,
    },
    game: {
      gameRoles: game.gameRoles,
      presentRoleIds: game.presentRoleIds,
    },
  }
}

/** Construct a complete GameRole with realistic defaults (no `as any`). */
function makeFullRole(roleId: number, name: string, emotion: string = '正常') {
  return {
    roleId,
    roleName: name,
    roleSubTitle: `${name}_sub`,
    thinkMessage: '',
    emotion,
    originalEmotion: emotion,
    scale: 1,
    offsetX: 0,
    offsetY: 0,
    bubbleTop: 0,
    bubbleLeft: 0,
    show: true,
    clothes: {},
    clothesName: '',
    bodyPart: {},
    character_folder: `chars/${name}`,
  }
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
  // Capture the anchor so tests can assert on its `download` attribute.
  let capturedAnchor: HTMLAnchorElement | null = null
  vi.spyOn(document, 'createElement').mockImplementation((tag: string) => {
    const el = origCreateElement(tag)
    if (tag === 'a') {
      el.click = clickSpy
      capturedAnchor = el as HTMLAnchorElement
    }
    return el
  })
  return {
    getCapturedBlob: () => capturedBlob,
    getAnchor: () => capturedAnchor,
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
      // v2 whitelist: replay extensions ARE exported (null when unset)
      expect(env.script.lines[0]).toHaveProperty('audio_path', null)
      expect(env.script.lines[0]).toHaveProperty('overlay', null)
      expect(env.script.lines[0]).toHaveProperty('stage_id', '')
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
      // The anchor's download attribute carries the timestamped filename.
      const anchor = cap.getAnchor()
      expect(anchor).not.toBeNull()
      expect(anchor!.download).toMatch(/^save-\d{8}-\d{6}\.a2d\.json$/)
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

  it('rejects empty file (Q15)', async () => {
    const store = useScriptStore()
    store.setPhase('idle')
    const file = new File([''], 'empty.json')
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('解析')
    // Store untouched
    expect(store.lines).toEqual([])
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
        gameRoles: { 1: makeFullRole(1, 'ema', '开心') },
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
        gameRoles: { 10: makeFullRole(10, 'ema') },
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

  it('v1→v2 compat: old snapshot lacking audio_path/overlay/stage_id imports with null defaults', async () => {
    const store = setIdle()
    // v1 snapshot: lines lack the v2 replay-extension fields entirely.
    const v1Env = {
      version: 1,
      exportedAt: new Date().toISOString(),
      script: {
        version: 1, exportedAt: new Date().toISOString(),
        lines: [
          { id: 'old1', speaker: 'ema', display_text: '旧文本', tts_text: '旧TTS', index: 0 },
          { id: 'old2', speaker: 'hiro', display_text: '旧文本2', tts_text: '旧TTS2', index: 1 },
        ],
        phase: 'idle', selectedLineId: null, playingLineId: null,
        editedText: {}, activeTab: 'review',
      },
      game: { gameRoles: {}, presentRoleIds: [] },
    }
    const file = new File([JSON.stringify(v1Env)], 'v1.json')
    const result = await importSession(file)
    expect(result.ok).toBe(true)
    expect(store.lines).toHaveLength(2)
    // v2 fields filled with null defaults for v1 snapshots.
    expect(store.lines[0].audio_path).toBeNull()
    expect(store.lines[0].overlay).toBeNull()
    expect(store.lines[0].stage_id).toBe('')
    expect(store.lines[1].audio_path).toBeNull()
  })

  it('round-trip preserves replay extensions (audio_path/overlay/stage_id)', async () => {
    const store = setIdle()
    const overlay = {
      line_id: 'r1', character_id: 1, ref_audio_path: null, gsv_params: null,
      sprite_positions: { ema: { x: 30, y: 60, scale: 1.2 } },
      background: 'bg_night.webp', text_overlays: [{ id: 't1', text: '标题', x: 50, y: 10, width: 0, font_size: 24, color: '#fff', opacity: 1, z: 0 }],
      image_overlays: [], bgm: 'bgm.mp3', bgm_volume: 0.8, bgm_loop: true,
    }
    store.addLine(makeLine('r1', 0, { audio_path: '/audio/r1.wav', overlay, stage_id: 's1' }))
    store.setPhase('paused')

    const cap = setupDownloadCapture()
    let env: any
    try {
      exportSession()
      env = await blobToJson(cap.getCapturedBlob()!)
    } finally {
      cap.restore()
    }

    // Export carries the replay extensions.
    expect(env.script.lines[0].audio_path).toBe('/audio/r1.wav')
    expect(env.script.lines[0].overlay).toMatchObject({ background: 'bg_night.webp' })
    expect(env.script.lines[0].stage_id).toBe('s1')

    // Import restores them.
    store.reset()
    const file = new File([JSON.stringify(env)], 'v2.json')
    const result = await importSession(file)
    expect(result.ok).toBe(true)
    expect(store.lines[0].audio_path).toBe('/audio/r1.wav')
    expect(store.lines[0].overlay).toMatchObject({ background: 'bg_night.webp' })
    expect(store.lines[0].stage_id).toBe('s1')
  })

  it('rejects unsupported version 999', async () => {
    setIdle()
    const file = new File([JSON.stringify({ version: 999, script: { lines: [] } })], 'v999.json')
    const result = await importSession(file)
    expect(result.ok).toBe(false)
    expect(result.error).toContain('不支持')
  })

  it('AC-1 negative: rejects line with non-string audio_path', async () => {
    setIdle()
    const env = {
      version: 2,
      script: {
        version: 2, exportedAt: '',
        lines: [{ id: 'bad', speaker: 'ema', display_text: 't', tts_text: 't', index: 0, audio_path: 123 }],
        phase: 'idle', selectedLineId: null, playingLineId: null,
        editedText: {}, activeTab: 'review' as const,
      },
      game: { gameRoles: {}, presentRoleIds: [] },
    }
    const result = await importSession(new File([JSON.stringify(env)], 'bad.json'))
    expect(result.ok).toBe(false)
    expect(result.error).toContain('结构不完整')
  })

  it('AC-1 negative: rejects line with malformed overlay image_overlays', async () => {
    setIdle()
    const env = {
      version: 2,
      script: {
        version: 2, exportedAt: '',
        lines: [{
          id: 'o1', speaker: 'ema', display_text: 't', tts_text: 't', index: 0,
          audio_path: null, stage_id: '',
          overlay: { image_overlays: [{ path: 'x.png' /* missing x/y/w/h/opacity/z */ }] },
        }],
        phase: 'idle', selectedLineId: null, playingLineId: null,
        editedText: {}, activeTab: 'review' as const,
      },
      game: { gameRoles: {}, presentRoleIds: [] },
    }
    const result = await importSession(new File([JSON.stringify(env)], 'bad.json'))
    expect(result.ok).toBe(false)
    expect(result.error).toContain('overlay')
  })
})

describe('addLine normalization (WS payload)', () => {
  it('fills null defaults for missing replay extensions', () => {
    const store = setIdle()
    // Simulate WS script_line payload: only core fields (no audio_path/overlay/stage_id).
    const wsPayload = { id: 'w1', speaker: 'ema', display_text: '文本', tts_text: 'TTS', index: 0 }
    store.addLine(wsPayload as ScriptLine)
    expect(store.lines[0].audio_path).toBeNull()
    expect(store.lines[0].overlay).toBeNull()
    expect(store.lines[0].stage_id).toBe('')
  })

  it('preserves present replay extensions', () => {
    const store = setIdle()
    const line = makeLine('k1', 0, { audio_path: '/audio/k1.wav', stage_id: 's1' })
    store.addLine(line)
    expect(store.lines[0].audio_path).toBe('/audio/k1.wav')
    expect(store.lines[0].stage_id).toBe('s1')
  })
})

describe('AC-4 performance', () => {
  function makeLines(n: number): ScriptLine[] {
    return Array.from({ length: n }, (_, i) => ({
      id: `l${i}`, speaker: 'ema', index: i,
      display_text: '一二三四五六七八九十'.repeat(5), // 50 chars
      tts_text: `TTS${i}`, emotion: '开心',
      audio_path: null, overlay: null, stage_id: '',
    }))
  }

  it('1000 lines export+import round-trips under 200ms', async () => {
    const store = setIdle()
    const lines = makeLines(1000)
    lines.forEach(l => store.addLine(l))
    const game = useGameStore()
    game.importFromSnapshot({
      gameRoles: { 1: makeFullRole(1, 'ema'), 2: makeFullRole(2, 'hiro') },
      presentRoleIds: [1, 2],
    })

    // Time the full export→import CPU path: JSON.stringify (export serialization)
    // + File construction + JSON.parse (import) + store fill. The Blob/anchor DOM
    // side effects are excluded (they touch the mocked DOM, not the CPU budget).
    const t0 = performance.now()
    const snapshot = buildSnapshot(store, game)
    const json = JSON.stringify(snapshot)
    store.reset()
    const file = new File([json], 'perf.json')
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
      gameRoles: { 5: makeFullRole(5, 'ema', '哭') },
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
