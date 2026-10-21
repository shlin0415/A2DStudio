import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { emitTrace } from '@/utils/a2d-trace'

// ── Types ──────────────────────────────────────────

/** Screen text overlay with percentage coordinates (0-100). Mirrors backend TextOverlay. */
export interface TextOverlay {
  id: string
  text: string
  x: number
  y: number
  width: number
  font_size: number
  color: string
  opacity: number
  z: number
}

/** Image overlay layer. Mirrors backend image_overlay dict shape. */
export interface ImageOverlay {
  id: string
  path: string
  x: number
  y: number
  w: number
  h: number
  opacity: number
  z: number
}

/** Per-line visual state. Mirrors backend LineOverlay (ling_chat/schemas/script_overlay.py). */
export interface LineOverlay {
  line_id: string
  character_id: number
  ref_audio_path: string | null
  gsv_params: Record<string, unknown> | null
  sprite_positions: Record<string, { x: number; y: number; scale: number }> | null
  background: string | null
  text_overlays: TextOverlay[]
  image_overlays: ImageOverlay[]
  bgm: string
  bgm_volume: number
  bgm_loop: boolean
}

export interface ScriptLine {
  id: string
  speaker: string
  emotion?: string
  display_text: string
  tts_text: string
  action?: string  // （动作描述）from LLM, shown when A2D_SHOW_ACTIONS != "0"
  index: number
  batch_index?: number
  batch_total?: number
  // ── P1 replay extensions (mirror backend ScriptLine) ──
  audio_path: string | null
  overlay: LineOverlay | null
  stage_id: string
}

export interface ErrorInfo {
  error_type: string
  message: string
  detail: string
  generation_id: string
  retry_count: number
  max_retries: number
  line_id?: string
  auto_play?: boolean
}

export type Phase = 'idle' | 'thinking' | 'translating' | 'synthesizing' | 'paused' | 'error'

/** Shape of the JSON snapshot produced by exportSession / consumed by importFromSnapshot. */
export interface ScriptSnapshot {
  version: number
  exportedAt: string
  projectName?: string
  lines: ScriptLine[]
  phase: Phase
  selectedLineId: string | null
  playingLineId: string | null
  editedText: Record<string, string>
  activeTab: 'script' | 'review' | 'event'
}

// ── Store ──────────────────────────────────────────

export const useScriptStore = defineStore('script', () => {
  const lines = ref<ScriptLine[]>([])
  const currentLine = ref<ScriptLine | null>(null)
  const phase = ref<Phase>('idle')
  const error = ref<ErrorInfo | null>(null)
  const generationId = ref<string | null>(null)
  const projectName = ref('未命名剧本')

  // Cross-tab editor state
  const selectedLineId = ref<string | null>(null)
  const editedText = ref<Record<string, string>>({})
  const activeTab = ref<'script' | 'review' | 'event'>('script')

  // Batch progress (multi-line generation)
  const batchIndex = ref(0)
  const batchTotal = ref(0)

  // Audio-subtitle sync: which line's audio is currently playing
  const playingLineId = ref<string | null>(null)
  const isAudioPlaying = ref(false)

  // P1 replay: stage_id -> default_background map (populated from import envelope).
  const stageMap = ref<Record<string, string>>({})

  const isThinking = computed(() => phase.value === 'thinking')
  const isTranslating = computed(() => phase.value === 'translating')
  const isSynthesizing = computed(() => phase.value === 'synthesizing')
  const isPaused = computed(() => phase.value === 'paused')
  const hasError = computed(() => phase.value === 'error')
  const isIdle = computed(() => phase.value === 'idle')
  // True when backend is busy (generating or synthesizing), button should be disabled
  const isBusy = computed(() => isThinking.value || isTranslating.value || isSynthesizing.value)

  function addLine(line: ScriptLine) {
    // Normalize: WS script_line payload carries only core fields (audio_path arrives
    // via tts_ready, overlay/stage_id via later flow). Fill defaults so every element
    // in lines[] satisfies the ScriptLine contract — replay engine reads these fields.
    const normalized: ScriptLine = {
      ...line,
      audio_path: line.audio_path ?? null,
      overlay: line.overlay ?? null,
      stage_id: line.stage_id ?? '',
    }
    lines.value.push(normalized)
    currentLine.value = normalized
    emitTrace('script_line', {
      lineId: normalized.id, speaker: normalized.speaker, index: normalized.index,
      batch_index: normalized.batch_index, batch_total: normalized.batch_total,
    })
    emitTrace('currentLine', { lineId: normalized.id, index: normalized.index })
    // Track batch progress (undefined = single-line or legacy)
    if (normalized.batch_index != null) batchIndex.value = normalized.batch_index
    if (normalized.batch_total != null) batchTotal.value = normalized.batch_total
  }

  function createManualLine(speaker: string): ScriptLine {
    const line: ScriptLine = {
      id: crypto.randomUUID(),
      speaker,
      display_text: '',
      tts_text: '',
      index: lines.value.length,
      audio_path: null,
      overlay: null,
      stage_id: '',
    }
    lines.value.push(line)
    currentLine.value = line
    selectedLineId.value = line.id
    phase.value = 'paused'
    activeTab.value = 'script'
    return line
  }

  function updateLine(
    lineId: string,
    updates: Partial<Pick<ScriptLine, 'speaker' | 'emotion' | 'display_text' | 'tts_text' | 'action'>>,
  ): void {
    const line = lines.value.find((candidate) => candidate.id === lineId)
    if (!line) return
    // Display text may differ from voice text; only actual synthesis inputs invalidate audio.
    const speechChanged = (updates.speaker !== undefined && updates.speaker !== line.speaker)
      || (updates.tts_text !== undefined && updates.tts_text !== line.tts_text)
    Object.assign(line, updates)
    if (speechChanged) line.audio_path = null
    if (currentLine.value?.id === lineId) currentLine.value = line
  }

  function setAudioPath(lineId: string, audioPath: string | null): void {
    const line = lines.value.find((candidate) => candidate.id === lineId)
    if (line) line.audio_path = audioPath
  }

  function removeLine(lineId: string): void {
    const removedIndex = lines.value.findIndex((line) => line.id === lineId)
    if (removedIndex < 0) return
    lines.value.splice(removedIndex, 1)
    lines.value.forEach((line, index) => { line.index = index })
    if (selectedLineId.value === lineId) {
      selectedLineId.value = lines.value[Math.min(removedIndex, lines.value.length - 1)]?.id ?? null
    }
    currentLine.value = lines.value[lines.value.length - 1] ?? null
    phase.value = 'paused'
  }

  function moveLine(lineId: string, offset: -1 | 1): void {
    const currentIndex = lines.value.findIndex((line) => line.id === lineId)
    const nextIndex = currentIndex + offset
    if (currentIndex < 0 || nextIndex < 0 || nextIndex >= lines.value.length) return
    const line = lines.value.splice(currentIndex, 1)[0]
    if (!line) return
    lines.value.splice(nextIndex, 0, line)
    lines.value.forEach((item, index) => { item.index = index })
    currentLine.value = line
  }

  function setActiveTab(tab: ScriptSnapshot['activeTab']): void {
    activeTab.value = tab
  }

  function setProjectName(name: string): void {
    projectName.value = name
  }

  function setPhase(newPhase: Phase) {
    const oldPhase = phase.value
    phase.value = newPhase
    emitTrace('phase_change', { from: oldPhase, to: newPhase })
    // Reset only when a new generation starts. The backend also emits thinking
    // between generated lines while earlier TTS is still playing, so resetting
    // on every thinking event loses the active presentation line mid-sentence.
    if (
      newPhase === 'thinking'
      && (oldPhase === 'idle' || oldPhase === 'paused' || oldPhase === 'error')
    ) {
      batchIndex.value = 0
      batchTotal.value = 0
      if (!isAudioPlaying.value) playingLineId.value = null
    }
  }

  function setError(err: ErrorInfo) {
    error.value = err
    setPhase('error')  // emits phase_change trace (was: phase.value = 'error')
  }

  function clearError() {
    error.value = null
  }

  // P1 replay: populate stageMap from imported envelope stages[].
  function setStageMap(map: Record<string, string>): void {
    stageMap.value = map || {}
  }

  function reset() {
    lines.value = []
    currentLine.value = null
    phase.value = 'idle'
    error.value = null
    generationId.value = null
    projectName.value = '未命名剧本'
    selectedLineId.value = null
    editedText.value = {}
    activeTab.value = 'script'
    batchIndex.value = 0
    batchTotal.value = 0
    playingLineId.value = null
    isAudioPlaying.value = false
    stageMap.value = {}
  }

  // ── Cross-tab editor helpers ────────────────────

  function selectLine(lineId: string) {
    selectedLineId.value = lineId
    activeTab.value = 'script'
  }

  function setEdited(lineId: string, text: string) {
    editedText.value[lineId] = text
  }

  function clearEdited(lineId: string) {
    delete editedText.value[lineId]
  }

  function commitEdits() {
    editedText.value = {}
    selectedLineId.value = null
  }

  // ── Import / Export snapshot ──────────────────────

  /**
   * Replace the entire store state from a validated snapshot.
   * PRE-CONDITION: caller must have called reset() first (full overwrite, not merge).
   * selectedLineId is silently dropped if it no longer exists in the imported lines.
   */
  function importFromSnapshot(snap: ScriptSnapshot) {
    // v1→v2 compat: old snapshots lack audio_path/overlay/stage_id — fill null defaults.
    lines.value = snap.lines.map(l => ({
      ...l,
      audio_path: l.audio_path ?? null,
      overlay: l.overlay ?? null,
      stage_id: l.stage_id ?? '',
    }))
    editedText.value = snap.editedText || {}
    projectName.value = snap.projectName || '未命名剧本'
    activeTab.value = snap.activeTab || 'script'
    // Both IDs must reference an existing line or be null — otherwise UI indicators dangle.
    const lineIds = new Set(snap.lines.map(l => l.id))
    selectedLineId.value = snap.selectedLineId && lineIds.has(snap.selectedLineId)
      ? snap.selectedLineId
      : null
    playingLineId.value = snap.playingLineId && lineIds.has(snap.playingLineId)
      ? snap.playingLineId
      : null
    const lastLine = snap.lines.length > 0 ? snap.lines[snap.lines.length - 1] : null
    currentLine.value = lastLine && lineIds.has(lastLine.id) ? lastLine : null
    // Contract: after import, always pause — caller (useA2DSaveLoad) relies on this.
    phase.value = 'paused'
  }

  const selectedLine = computed(() => {
    if (!selectedLineId.value) return null
    return lines.value.find(l => l.id === selectedLineId.value) || null
  })

  // The line currently being spoken (audio-synced during playback)
  const playingLine = computed(() => {
    if (!playingLineId.value) return null
    return lines.value.find(l => l.id === playingLineId.value) || null
  })

  return {
    lines, currentLine, phase, error, generationId, projectName,
    selectedLineId, editedText, activeTab, selectedLine, stageMap,
    batchIndex, batchTotal, playingLineId, isAudioPlaying, playingLine,
    isThinking, isTranslating, isSynthesizing, isPaused, hasError, isIdle, isBusy,
    addLine, createManualLine, updateLine, setAudioPath, removeLine, moveLine,
    setActiveTab, setProjectName,
    setPhase, setError, clearError, reset, setStageMap,
    selectLine, setEdited, clearEdited, commitEdits, importFromSnapshot,
  }
})
