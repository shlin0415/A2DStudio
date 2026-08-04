import { ref, computed, type Ref } from 'vue'
import { useScriptStore } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import { audioQueue, isAudioPlaying } from '@/composables/audio-queue'
import { playNextInQueue, setReplayActive } from '@/composables/useA2DWebSocket'
import { resolveVisual } from '@/composables/overlay-resolve'
import type { ResolvedLineVisual } from '@/composables/types'
import type { ReplayState } from '@/composables/types'
import type { ScriptLine } from '@/stores/modules/script'

// ── Singleton state (module-level, like useA2DWebSocket) ────
let _state: Ref<ReplayState> | null = null
let _replayLines: Ref<ScriptLine[]> | null = null
let _visuals: Ref<ResolvedLineVisual[]> | null = null
let _currentSubtitle: Ref<string> | null = null
let _error: Ref<string | null> | null = null
let _initialized = false

function ensureInit() {
  if (_initialized) return
  _state = ref<ReplayState>('idle')
  _replayLines = ref<ScriptLine[]>([])
  _visuals = ref<ResolvedLineVisual[]>([])
  _currentSubtitle = ref('')
  _error = ref<string | null>(null)
  _initialized = true
}

/**
 * Replay engine — state machine driving sequential playback of imported script.
 *
 * States: idle → loading → playing ↔ paused → seeking → idle
 * Index is derived from store.playingLineId (single source of truth).
 * Singleton: import anywhere to access shared replay state.
 */
export function useA2DReplay() {
  ensureInit()
  const scriptStore = useScriptStore()
  const gameStore = useGameStore()

  const state = _state!
  const replayLines = _replayLines!
  const currentSubtitle = _currentSubtitle!
  const error = _error!

  // Derived index from playingLineId (single source of truth per deliberation #8).
  const currentIndex = computed(() => {
    const id = scriptStore.playingLineId
    if (!id) return -1
    return replayLines.value.findIndex(l => l.id === id)
  })

  const isPlaying = computed(() => state.value === 'playing')
  const isPaused = computed(() => state.value === 'paused')

  /** Begin replay from a start index. */
  function start(startIndex = 0) {
    if (scriptStore.lines.length === 0) {
      error.value = '无内容可重播'
      return
    }
    if (startIndex < 0 || startIndex >= scriptStore.lines.length) return

    state.value = 'loading'
    error.value = null
    replayLines.value = [...scriptStore.lines]
    // Subtitle + emotion for the first item are set by onItemStart (fired inside
    // playNextInQueue at item start).

    const startLine = replayLines.value[startIndex]
    if (!startLine) return
    scriptStore.playingLineId = startLine.id

    // Take ownership of the audio queue.
    setReplayActive(true)
    state.value = 'playing'

    // Enqueue audio for sequential playback.
    enqueueFromIndex(startIndex)
  }

  /** Enqueue audio items from startIndex onward. */
  function enqueueFromIndex(startIndex: number) {
    for (let i = startIndex; i < replayLines.value.length; i++) {
      const line = replayLines.value[i]
      if (!line) break
      if (!line.audio_path) continue // missing audio: skip (AC-7)
      const url = line.audio_path.startsWith('/')
        ? `http://${window.location.hostname}:8765${line.audio_path}`
        : line.audio_path
      audioQueue.value.push({ url, lineId: line.id })
    }
    if (!isAudioPlaying.value) {
      playNextInQueue(scriptStore, onItemStart)
    }
  }

  /** Replay engine hook: sync subtitle + emotion when an audio item starts. */
  function onItemStart(line: ScriptLine) {
    currentSubtitle.value = line.display_text
    applyEmotion(line)
  }

  function pause() {
    if (state.value !== 'playing') return
    state.value = 'paused'
  }

  function resume() {
    if (state.value !== 'paused') return
    state.value = 'playing'
    if (!isAudioPlaying.value) playNextInQueue(scriptStore)
  }

  function seek(index: number) {
    if (index < 0 || index >= replayLines.value.length) return
    const prevState = state.value
    state.value = 'seeking'
    audioQueue.value.length = 0
    const line = replayLines.value[index]
    if (!line) { state.value = prevState; return }
    scriptStore.playingLineId = line.id
    currentSubtitle.value = line.display_text
    applyEmotion(line)
    state.value = prevState === 'paused' ? 'paused' : 'playing'
    if (state.value === 'playing') enqueueFromIndex(index)
  }

  function stop() {
    state.value = 'idle'
    audioQueue.value.length = 0
    currentSubtitle.value = ''
    scriptStore.playingLineId = null
    setReplayActive(false)
  }

  /** Advance to next line (called on audio_end). Returns false if replay ended. */
  function advance(): boolean {
    const nextIdx = currentIndex.value + 1
    if (nextIdx >= replayLines.value.length) {
      stop()
      return false
    }
    const line = replayLines.value[nextIdx]
    if (!line) { stop(); return false }
    scriptStore.playingLineId = line.id
    currentSubtitle.value = line.display_text
    applyEmotion(line)
    return true
  }

  /** Apply emotion for the current line to gameRoles (AC-3). */
  function applyEmotion(line: ScriptLine) {
    const speaker = line.speaker
    const emotion = line.emotion
    if (!speaker || !emotion) return
    const roleId = findRoleIdForSpeaker(speaker)
    if (roleId != null && gameStore.gameRoles[roleId]) {
      gameStore.gameRoles[roleId].emotion = emotion
      gameStore.gameRoles[roleId].originalEmotion = emotion
    }
  }

  function findRoleIdForSpeaker(speaker: string): number | null {
    for (const role of Object.values(gameStore.gameRoles)) {
      if (role.roleName === speaker || String(role.roleId) === speaker) return role.roleId
    }
    return null
  }

  return {
    state, currentIndex, currentSubtitle, error,
    isPlaying, isPaused,
    start, pause, resume, seek, stop, advance,
  }
}

/** Reset singleton state (TEST-ONLY: isolates replay engine between test cases). */
export function _resetReplaySingleton() {
  if (_state) _state.value = 'idle'
  if (_replayLines) _replayLines.value = []
  if (_visuals) _visuals.value = []
  if (_currentSubtitle) _currentSubtitle.value = ''
  if (_error) _error.value = null
}
