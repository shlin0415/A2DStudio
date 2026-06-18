import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// ── Types ──────────────────────────────────────────

export interface ScriptLine {
  id: string
  speaker: 'ema' | 'hiro'
  emotion?: string
  display_text: string
  tts_text: string
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

// ── Store ──────────────────────────────────────────

export const useScriptStore = defineStore('script', () => {
  const lines = ref<ScriptLine[]>([])
  const currentLine = ref<ScriptLine | null>(null)
  const phase = ref<Phase>('idle')
  const error = ref<ErrorInfo | null>(null)
  const generationId = ref<string | null>(null)
  const consecutiveErrors = ref(0)

  // Cross-tab editor state
  const selectedLineId = ref<string | null>(null)
  const editedText = ref<Record<string, string>>({})
  const activeTab = ref<'review' | 'event'>('review')

  // Batch progress (multi-line generation)
  const batchIndex = ref(0)
  const batchTotal = ref(0)

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
    // Track batch progress (undefined = single-line or legacy)
    if (line.batch_index != null) batchIndex.value = line.batch_index
    if (line.batch_total != null) batchTotal.value = line.batch_total
  }

  function setPhase(newPhase: Phase) {
    phase.value = newPhase
  }

  function setError(err: ErrorInfo) {
    error.value = err
    phase.value = 'error'
    consecutiveErrors.value++
  }

  function clearError() {
    error.value = null
    consecutiveErrors.value = 0
  }

  function reset() {
    lines.value = []
    currentLine.value = null
    phase.value = 'idle'
    error.value = null
    generationId.value = null
    consecutiveErrors.value = 0
    selectedLineId.value = null
    editedText.value = {}
    activeTab.value = 'review'
    batchIndex.value = 0
    batchTotal.value = 0
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

  const selectedLine = computed(() => {
    if (!selectedLineId.value) return null
    return lines.value.find(l => l.id === selectedLineId.value) || null
  })

  return {
    lines, currentLine, phase, error, generationId, consecutiveErrors,
    selectedLineId, editedText, activeTab, selectedLine,
    batchIndex, batchTotal,
    isThinking, isTranslating, isSynthesizing, isPaused, hasError, isIdle, isBusy,
    addLine, setPhase, setError, clearError, reset,
    selectLine, setEdited, clearEdited, commitEdits,
  }
})
