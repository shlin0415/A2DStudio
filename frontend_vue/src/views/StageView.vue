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
import { computed } from 'vue'
import { GameBackground, GameRolesStage, GameDialog, StageOverlay } from '@/components/game/standard'
import ScriptPanel from '@/components/game/ScriptPanel.vue'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'
import { useScriptStore } from '@/stores/modules/script'
import { resolveVisual } from '@/composables/overlay-resolve'

// WS lifecycle: auto-connect on mount, singleton shared with child components
useA2DWebSocket()

// P1: derive visual from selected line (M3 replay engine will drive from playingLineId).
const scriptStore = useScriptStore()
const currentVisual = computed(() => {
  const line = scriptStore.selectedLine
  return resolveVisual(line)
})
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
