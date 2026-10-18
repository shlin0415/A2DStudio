<template>
  <div class="stage-view" :class="{ 'stage-view--focused': isFocusedPlayback }">
    <!-- Reuse only the visual stage layers; the LingChat chat dialog belongs to /chat. -->
    <GameBackground />
    <GameRolesStage />

    <!-- A2D project visuals and subtitles remain visible in both modes. -->
    <StageOverlay :visual="currentVisual" />
    <SubtitleOverlay :text="replaySubtitle" :is-narrator="isNarrator" />

    <div class="stage-toolbar">
      <button
        v-if="!isFocusedPlayback"
        data-testid="enter-focused-playback"
        type="button"
        @click="enterFocusedPlayback"
      >
        专注播放
      </button>
      <button
        v-else
        data-testid="leave-focused-playback"
        type="button"
        @click="leaveFocusedPlayback"
      >
        停止并返回编辑
      </button>
    </div>

    <div
      v-if="isFocusedPlayback"
      class="focused-playback-controls"
      data-testid="focused-playback-controls"
      role="group"
      aria-label="专注播放控制"
    >
      <button
        v-if="isReplayPlaying"
        data-testid="focus-pause"
        type="button"
        @click="replay.pause"
      >
        暂停
      </button>
      <button
        v-else-if="isReplayPaused"
        data-testid="focus-resume"
        type="button"
        @click="replay.resume"
      >
        继续
      </button>
      <button
        v-else
        data-testid="focus-play"
        type="button"
        :disabled="scriptStore.lines.length === 0"
        @click="startReplay"
      >
        播放
      </button>
      <button
        data-testid="focus-stop"
        type="button"
        :disabled="!isReplayPlaying && !isReplayPaused"
        @click="replay.stop"
      >
        停止
      </button>
      <span v-if="replayError" role="status">{{ replayError }}</span>
    </div>

    <!-- v-show keeps the editor's tab and form state when switching modes. -->
    <ScriptPanel v-show="!isFocusedPlayback" />
  </div>
</template>

<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { GameBackground, GameRolesStage, StageOverlay, SubtitleOverlay } from '@/components/game/standard'
import ScriptPanel from '@/components/game/ScriptPanel.vue'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'
import { useA2DReplay } from '@/composables/useA2DReplay'
import { commitImport } from '@/composables/useA2DSaveLoad'
import { useScriptStore } from '@/stores/modules/script'
import { useSettingsStore } from '@/stores/modules/settings'
import { resolveVisual } from '@/composables/overlay-resolve'
import type { ScriptLine } from '@/stores/modules/script'

// WS lifecycle: auto-connect on mount, singleton shared with child components
useA2DWebSocket()

// P1 replay engine (singleton). Transport controls in ReviewPanel/EventTrack.
const replay = useA2DReplay()
const replaySubtitle = replay.currentSubtitle
const isFocusedPlayback = ref(false)
const isReplayPlaying = computed(() => replay.isPlaying.value)
const isReplayPaused = computed(() => replay.isPaused.value)
const replayError = computed(() => replay.error.value)

const scriptStore = useScriptStore()
const settingsStore = useSettingsStore()

function enterFocusedPlayback() {
  isFocusedPlayback.value = true
}

function leaveFocusedPlayback() {
  replay.stop()
  isFocusedPlayback.value = false
}

function startReplay() {
  commitImport()
  const selectedLineIndex = scriptStore.lines.findIndex(
    (line) => line.id === scriptStore.selectedLineId,
  )
  replay.start(selectedLineIndex >= 0 ? selectedLineIndex : 0)
}

// stageMap: stage_id -> default_background, sourced from the imported envelope
// stages[] via scriptStore (populated in importSession).
const stageMap = computed<Record<string, string>>(() => scriptStore.stageMap)

// M3 replay engine will switch this source to playingLineId.
const playingLine = computed<ScriptLine | null>(() => {
  const id = scriptStore.playingLineId
  if (!id) return scriptStore.selectedLine // M2 preview fallback
  return scriptStore.lines.find(l => l.id === id) ?? null
})

// Derive narrator styling from current playing line's speaker.
const isNarrator = computed(() => playingLine.value?.speaker === 'narrator')

const currentVisual = computed(() => {
  // globalDefault from settingsStore (user-set current background).
  return resolveVisual(playingLine.value, stageMap.value, settingsStore.currentBackground || '')
})

// Drive GameBackground via settingsStore (reuses ImageAcrossFade crossfade).
// Background sits BELOW characters (correct layering) — not in StageOverlay.
watch(currentVisual, (v) => {
  if (v?.background) settingsStore.setCurrentBackground(v.background)
}, { immediate: true })
</script>

<style scoped>
.stage-view {
  position: absolute;
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  overflow: hidden;
}

.stage-toolbar,
.focused-playback-controls {
  position: absolute;
  z-index: 40;
  display: flex;
  align-items: center;
  gap: 8px;
}

.stage-toolbar {
  top: 16px;
  right: 16px;
}

.focused-playback-controls {
  bottom: 24px;
  left: 50%;
  transform: translateX(-50%);
  padding: 10px 14px;
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 10px;
  background: rgba(10, 10, 20, 0.9);
  color: #fff;
}

.stage-toolbar button,
.focused-playback-controls button {
  border: 1px solid rgba(255, 255, 255, 0.24);
  border-radius: 6px;
  padding: 8px 12px;
  background: rgba(10, 10, 20, 0.88);
  color: #fff;
  cursor: pointer;
}

.stage-toolbar button:hover,
.focused-playback-controls button:hover:not(:disabled) {
  background: rgba(50, 65, 90, 0.95);
}

.focused-playback-controls button:disabled {
  cursor: not-allowed;
  opacity: 0.5;
}
</style>
