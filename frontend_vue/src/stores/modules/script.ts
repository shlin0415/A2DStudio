import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { emitTrace } from '@/utils/a2d-trace'

// ── Types ──────────────────────────────────────────

export interface ScriptLine {
  id: string
  speaker: 'ema' | 'hiro' | 'narrator'
  emotion?: string
  display_text: string
  tts_text: string
  action?: string  // （动作描述）from LLM, shown when A2D_SHOW_ACTIONS != "0"
  index: number
  batch_index?: number
  batch_total?: number
}

export interface ErrorInfo {
  error_type: string
  message: string
  detail: string
  generation_id: string
  retry_count: number
  max_retries: number
}

export type Phase = 'idle' | 'thinking' | 'translating' | 'synthesizing' | 'paused' | 'error'

/** Shape of the JSON snapshot produced by exportSession / consumed by importFromSnapshot. */
export interface ScriptSnapshot {
  version: number
  exportedAt: string
  lines: ScriptLine[]
  phase: Phase
  selectedLineId: string | null
  playingLineId: string | null
  editedText: Record<string, string>
  activeTab: 'review' | 'event'
}

// ── Store ──────────────────────────────────────────

export const useScriptStore = defineStore('script', () => {
  const lines = ref<ScriptLine[]>([])
  const currentLine = ref<ScriptLine | null>(null)
  const phase = ref<Phase>('idle')
  const error = ref<ErrorInfo | null>(null)
  const generationId = ref<string | null>(null)

  // Cross-tab editor state
  const selectedLineId = ref<string | null>(null)
  const editedText = ref<Record<string, string>>({})
  const activeTab = ref<'review' | 'event'>('review')

  // Batch progress (multi-line generation)
  const batchIndex = ref(0)
  const batchTotal = ref(0)

  // Audio-subtitle sync: which line's audio is currently playing
  const playingLineId = ref<string | null>(null)
  const isAudioPlaying = ref(false)

  const isThinking = computed(() => phase.value === 'thinking')
  const isTranslating = computed(() => phase.value === 'translating')
  const isSynthesizing = computed(() => phase.value === 'synthesizing')
  const isPaused = computed(() => phase.value === 'paused')
  const hasError = computed(() => phase.value === 'error')
  const isIdle = computed(() => phase.value === 'idle')
  // True when backend is busy (generating or synthesizing), button should be disabled
  const isBusy = computed(() => isThinking.value || isTranslating.value || isSynthesizing.value)

  function addLine(line: ScriptLine) {
    lines.value.push(line)
    currentLine.value = line
    emitTrace('script_line', {
      lineId: line.id, speaker: line.speaker, index: line.index,
      batch_index: line.batch_index, batch_total: line.batch_total,
    })
    emitTrace('currentLine', { lineId: line.id, index: line.index })
    // Track batch progress (undefined = single-line or legacy)
    if (line.batch_index != null) batchIndex.value = line.batch_index
    if (line.batch_total != null) batchTotal.value = line.batch_total
  }

  function setPhase(newPhase: Phase) {
    const oldPhase = phase.value
    phase.value = newPhase
    emitTrace('phase_change', { from: oldPhase, to: newPhase })
    // Clear batch progress and audio state at start of each batch
    if (newPhase === 'thinking') {
      batchIndex.value = 0
      batchTotal.value = 0
      playingLineId.value = null
      isAudioPlaying.value = false
    }
  }

  function setError(err: ErrorInfo) {
    error.value = err
    setPhase('error')  // emits phase_change trace (was: phase.value = 'error')
  }

  function clearError() {
    error.value = null
  }

  function reset() {
    lines.value = []
    currentLine.value = null
    phase.value = 'idle'
    error.value = null
    generationId.value = null
    selectedLineId.value = null
    editedText.value = {}
    activeTab.value = 'review'
    batchIndex.value = 0
    batchTotal.value = 0
    playingLineId.value = null
    isAudioPlaying.value = false
  }

  // ── Cross-tab editor helpers ────────────────────

  function selectLine(lineId: string) {
    selectedLineId.value = lineId
    activeTab.value = 'review'
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
    lines.value = snap.lines
    editedText.value = snap.editedText || {}
    activeTab.value = snap.activeTab || 'review'
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
    lines, currentLine, phase, error, generationId,
    selectedLineId, editedText, activeTab, selectedLine,
    batchIndex, batchTotal, playingLineId, isAudioPlaying, playingLine,
    isThinking, isTranslating, isSynthesizing, isPaused, hasError, isIdle, isBusy,
    addLine, setPhase, setError, clearError, reset,
    selectLine, setEdited, clearEdited, commitEdits, importFromSnapshot,
  }
})
