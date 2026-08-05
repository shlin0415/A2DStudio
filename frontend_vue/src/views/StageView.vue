<template>
  <div class="stage-view">
    <!-- LingChat standard: background + multi-character stage + dialog -->
    <GameBackground />
    <GameRolesStage />
    <GameDialog />

    <!-- P1 replay overlay: renders per-line visual (background/text/image). -->
    <StageOverlay :visual="currentVisual" />

    <!-- P1 replay subtitle: current line display_text synced to playback. -->
    <SubtitleOverlay :text="replaySubtitle" :is-narrator="isNarrator" />

    <!-- A2D overlay: script editor panel at bottom -->
    <ScriptPanel />
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { GameBackground, GameRolesStage, GameDialog, StageOverlay, SubtitleOverlay } from '@/components/game/standard'
import ScriptPanel from '@/components/game/ScriptPanel.vue'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'
import { useA2DReplay } from '@/composables/useA2DReplay'
import { useScriptStore } from '@/stores/modules/script'
import { useSettingsStore } from '@/stores/modules/settings'
import { resolveVisual } from '@/composables/overlay-resolve'
import type { ScriptLine } from '@/stores/modules/script'

// WS lifecycle: auto-connect on mount, singleton shared with child components
useA2DWebSocket()

// P1 replay engine (singleton). Transport controls in ReviewPanel/EventTrack.
const replay = useA2DReplay()
const replaySubtitle = replay.currentSubtitle

const scriptStore = useScriptStore()
const settingsStore = useSettingsStore()

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
</style>
