<!--
  StageOverlay — P1/P4 shared visual rendering layer.

  P1 (replay, editable=false): pure presentational consumer of ResolvedLineVisual.
  P4 (editor, editable=true): adds drag handles + property inspector, emits overlay-change.

  Component contract:
    - Input: pre-resolved ResolvedLineVisual (engine runs line>stage>global priority chain)
    - Output: overlay-change event (editable mode only)
    - NEVER contains contenteditable (editing is P4-only)
    - NEVER owns audio (audio lives in useA2DWebSocket queue)
-->
<template>
  <div class="stage-overlay">
    <!-- P1 skeleton: rendering slots filled in M3. -->
  </div>
</template>

<script setup lang="ts">
import type { ResolvedLineVisual } from '@/composables/types'

withDefaults(defineProps<{
  visual: ResolvedLineVisual | null
  editable?: boolean
  stageSize?: { width: number; height: number }
}>(), {
  editable: false,
  stageSize: () => ({ width: 1920, height: 1080 }),
})

const emit = defineEmits<{
  (e: 'overlay-change', visual: ResolvedLineVisual): void
}>()

// Percentage (0-100) → pixel conversion happens in M3 per-element positioning.
</script>

<style scoped>
.stage-overlay {
  position: absolute;
  inset: 0;
  /* P1 (replay): pointer-events pass-through so clicks reach GameRolesStage. */
  pointer-events: none;
  overflow: hidden;
  z-index: 15;
}
</style>
