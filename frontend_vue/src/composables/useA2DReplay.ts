import { ref, computed, watch, type Ref } from 'vue'
import { useScriptStore } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import { audioQueue, isAudioPlaying } from '@/composables/audio-queue'
import { playNextInQueue, setReplayActive, pauseCurrentAudio, stopCurrentAudio, mainAudioPlay } from '@/composables/useA2DWebSocket'
import { playBGM, stopBGM } from '@/composables/useA2DBGM'
import type { ReplayState } from '@/composables/types'
import type { ScriptLine } from '@/stores/modules/script'

// ── Singleton state (module-level, like useA2DWebSocket) ────
let _state: Ref<ReplayState> | null = null
let _replayLines: Ref<ScriptLine[]> | null = null
let _currentSubtitle: Ref<string> | null = null
let _error: Ref<string | null> | null = null
let _skippedLines: Ref<string[]> | null = null
let _initialized = false

function ensureInit() {
  if (_initialized) return
  _state = ref<ReplayState>('idle')
  _replayLines = ref<ScriptLine[]>([])
  _currentSubtitle = ref('')
  _error = ref<string | null>(null)
  _skippedLines = ref<string[]>([])
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
  const skippedLines = _skippedLines!

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

    // AC-7: all lines missing audio -> finite idle + error (no stuck playing state).
    const hasAnyAudio = scriptStore.lines.some(l => l.audio_path)
    if (!hasAnyAudio) {
      error.value = '所有行均缺失音频'
      return
    }

    // MG-DOUBLEQUEUE: reset any in-flight playback so a restart never
    // double-queues (AC-6 negative test). Mirror stop()'s queue/audio reset.
    stopCurrentAudio()
    audioQueue.value = []
    isAudioPlaying.value = false
    _skippedLines!.value = []

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
    for (const line of replayLines.value.slice(startIndex)) {
      if (!line.audio_path) {
        // AC-7: track skipped lines for UI hint.
        skippedLines.value.push(line.id)
        continue
      }
      const url = line.audio_path.startsWith('/')
        ? `http://${window.location.hostname}:8765${line.audio_path}`
        : line.audio_path
      audioQueue.value.push({ url, lineId: line.id })
    }
    if (!isAudioPlaying.value) {
      playNextInQueue(scriptStore, onItemStart, onEnded)
    }
  }

  /** Sync subtitle + emotion + sprites + BGM for the active line (single source of truth). */
  function syncVisual(line: ScriptLine): void {
    currentSubtitle.value = line.display_text
    applyEmotion(line)
    applySpritePositions(line)
    applyBGM(line)
  }

  /** Replay engine hook: sync visual when an audio item starts. */
  function onItemStart(line: ScriptLine) {
    syncVisual(line)
  }

  /** On each audio end: advance the state machine. Returns false at replay end. */
  function onEnded() {
    advance()
  }

  // Defense-in-depth: re-sync on playingLineId change (guards against B1 callback-thread regression).
  watch(() => scriptStore.playingLineId, (id) => {
    if (!id) return
    const line = scriptStore.lines.find(l => l.id === id)
    if (line) syncVisual(line)
  })

  function pause() {
    if (state.value !== 'playing') return
    state.value = 'paused'
    pauseCurrentAudio() // B3: actually pause the audio element
  }

  function resume() {
    if (state.value !== 'paused') return
    state.value = 'playing'
    if (!isAudioPlaying.value) {
      playNextInQueue(scriptStore, onItemStart, onEnded)
    } else {
      mainAudioPlay() // B3: resume the paused audio element
    }
  }

  function seek(index: number) {
    if (index < 0 || index >= replayLines.value.length) return
    const prevState = state.value
    state.value = 'seeking'
    stopCurrentAudio() // B4: pause active audio before switching (prevents overlap)
    isAudioPlaying.value = false // MG5: reset so enqueueFromIndex starts playback
    audioQueue.value.length = 0
    const line = replayLines.value[index]
    if (!line) { state.value = prevState; return }
    scriptStore.playingLineId = line.id
    syncVisual(line)
    state.value = prevState === 'paused' ? 'paused' : 'playing'
    if (state.value === 'playing') enqueueFromIndex(index)
  }

  function stop() {
    state.value = 'idle'
    stopCurrentAudio() // B4: pause active audio
    isAudioPlaying.value = false // MG4: reset so a subsequent start() can play
    audioQueue.value.length = 0
    currentSubtitle.value = ''
    scriptStore.playingLineId = null
    // MG2: reset emotion to idle for all roles (AC-3 negative test).
    for (const role of Object.values(gameStore.gameRoles)) {
      role.emotion = '正常'
      role.originalEmotion = '正常'
    }
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
    syncVisual(line)
    return true
  }

  /** Apply per-line BGM to the audio element (AC-4). */
  function applyBGM(line: ScriptLine): void {
    const bgm = line.overlay?.bgm
    if (bgm) {
      const vol = line.overlay?.bgm_volume
      const loop = line.overlay?.bgm_loop ?? true
      playBGM(bgm, { volume: vol ?? 1, loop })
    } else {
      stopBGM()
    }
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

  /** Apply per-line sprite positions to gameRoles (AC-4 b-axis). */
  function applySpritePositions(line: ScriptLine): void {
    const sprites = line.overlay?.sprite_positions
    if (!sprites) return
    for (const [speaker, pos] of Object.entries(sprites)) {
      const roleId = findRoleIdForSpeaker(speaker)
      if (roleId != null && gameStore.gameRoles[roleId]) {
        const role = gameStore.gameRoles[roleId]
        if (pos.x != null) role.offsetX = pos.x
        if (pos.y != null) role.offsetY = pos.y
        if (pos.scale != null) role.scale = pos.scale
      }
    }
  }

  function findRoleIdForSpeaker(speaker: string): number | null {
    for (const role of Object.values(gameStore.gameRoles)) {
      if (role.roleName === speaker || String(role.roleId) === speaker) return role.roleId
    }
    return null
  }

  return {
    state, currentIndex, currentSubtitle, error, skippedLines,
    isPlaying, isPaused,
    start, pause, resume, seek, stop, advance,
  }
}

/** Reset singleton state (TEST-ONLY: isolates replay engine between test cases). */
export function _resetReplaySingleton() {
  if (_state) _state.value = 'idle'
  if (_replayLines) _replayLines.value = []
  if (_currentSubtitle) _currentSubtitle.value = ''
  if (_error) _error.value = null
  stopBGM()
}
