<template>
  <div class="stage-view">
    <!-- LingChat standard: background + multi-character stage + dialog -->
    <GameBackground />
    <GameRolesStage />
    <GameDialog />

    <!-- P1 replay overlay: renders per-line visual (background/text/image). -->
    <StageOverlay :visual="currentVisual" />

    <!-- A2D overlay: script editor panel at bottom -->
    <ScriptPanel />
  </div>
</template>

<script setup lang="ts">
import { computed, watch } from 'vue'
import { GameBackground, GameRolesStage, GameDialog, StageOverlay } from '@/components/game/standard'
import ScriptPanel from '@/components/game/ScriptPanel.vue'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'
import { useScriptStore } from '@/stores/modules/script'
import { useSettingsStore } from '@/stores/modules/settings'
import { resolveVisual } from '@/composables/overlay-resolve'
import type { ScriptLine } from '@/stores/modules/script'

// WS lifecycle: auto-connect on mount, singleton shared with child components
useA2DWebSocket()

const scriptStore = useScriptStore()
const settingsStore = useSettingsStore()

// stageMap: stage_id -> default_background. M3 task9 MUST replace with real map
// parsed from the replay envelope's stages[]. Currently empty (line-only fallback).
const stageMap = computed<Record<string, string>>(() => {
  // TODO(M3): parse stage_id -> default_background from replay envelope stages
  return {}
})

// M3 replay engine will switch this source to playingLineId.
const playingLine = computed<ScriptLine | null>(() => {
  const id = scriptStore.playingLineId
  if (!id) return scriptStore.selectedLine // M2 preview fallback
  return scriptStore.lines.find(l => l.id === id) ?? null
})

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
