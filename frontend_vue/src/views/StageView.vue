<template>
  <div class="stage-view">
    <!-- LingChat standard: background + multi-character stage + dialog -->
    <GameBackground />
    <GameRolesStage />
    <GameDialog />

    <!-- A2D overlay: script editor panel at bottom -->
    <ScriptPanel />
  </div>
</template>

<script setup lang="ts">
import { GameBackground, GameRolesStage, GameDialog } from '@/components/game/standard'
import ScriptPanel from '@/components/game/ScriptPanel.vue'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'

// WS lifecycle: auto-connect on mount, singleton shared with child components
useA2DWebSocket()
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
