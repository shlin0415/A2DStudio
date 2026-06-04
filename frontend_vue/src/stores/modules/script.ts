import { defineStore } from 'pinia'
import { ref, computed } from 'vue'

// ── Types ──────────────────────────────────────────

export interface ScriptLine {
  id: string
  speaker: 'ema' | 'hiro'
  display_text: string
  tts_text: string
  index: number
}

export interface ErrorInfo {
  error_type: string
  message: string
  detail: string
  generation_id: string
  retry_count: number
  max_retries: number
}

export type Phase = 'idle' | 'thinking' | 'synthesizing' | 'paused' | 'error'

// ── Store ──────────────────────────────────────────

export const useScriptStore = defineStore('script', () => {
  const lines = ref<ScriptLine[]>([])
  const currentLine = ref<ScriptLine | null>(null)
  const phase = ref<Phase>('idle')
  const error = ref<ErrorInfo | null>(null)
  const generationId = ref<string | null>(null)
  const consecutiveErrors = ref(0)

  const isThinking = computed(() => phase.value === 'thinking')
  const isSynthesizing = computed(() => phase.value === 'synthesizing')
  const isPaused = computed(() => phase.value === 'paused')
  const hasError = computed(() => phase.value === 'error')
  const isIdle = computed(() => phase.value === 'idle')

  function addLine(line: ScriptLine) {
    lines.value.push(line)
    currentLine.value = line
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
  }

  return {
    lines, currentLine, phase, error, generationId, consecutiveErrors,
    isThinking, isSynthesizing, isPaused, hasError, isIdle,
    addLine, setPhase, setError, clearError, reset,
  }
})
