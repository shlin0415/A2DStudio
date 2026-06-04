<template>
  <div class="stage-view">
    <StageCanvas />
  </div>
</template>

<script setup lang="ts">
import StageCanvas from '@/components/game/StageCanvas.vue'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'

// WS lifecycle: connect on mount, disconnect on unmount
useA2DWebSocket()
</script>

<style scoped>
.stage-view {
  width: 100vw;
  height: 100vh;
  overflow: hidden;
}
</style>
