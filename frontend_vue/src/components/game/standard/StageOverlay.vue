<!--
  StageOverlay — P1/P4 shared visual rendering layer.

  P1 (replay, editable=false): pure presentational consumer of ResolvedLineVisual.
  P4 (editor, editable=true): adds drag handles + property inspector, emits overlay-change.

  Component contract:
    - Input: pre-resolved ResolvedLineVisual (engine runs line>stage>global priority chain)
    - Output: overlay-change event (editable mode only)
    - NEVER contains contenteditable (editing is P4-only)
    - NEVER owns audio or sprite positioning (sprites via GameRoleAvatar props, BGM via useA2DBGM)
-->
<template>
  <div class="stage-overlay">
    <!-- Image overlays (static — non-editable in P1). z-index:15 is correct for
         overlay layers (above GameRolesStage, below GameDialog). -->
    <img
      v-for="img in visual?.imageOverlays ?? []"
      :key="img.id"
      :src="img.path"
      class="stage-overlay__image"
      :style="{
        left: img.x + '%', top: img.y + '%',
        width: img.w + 'px', height: img.h + 'px',
        opacity: img.opacity, zIndex: img.z,
      }"
      alt=""
    />

    <!-- Screen text overlays (static — non-editable in P1). -->
    <div
      v-for="t in visual?.textOverlays ?? []"
      :key="t.id"
      class="stage-overlay__text"
      :style="{
        left: t.x + '%', top: t.y + '%',
        width: t.width ? t.width + 'px' : 'auto',
        fontSize: t.fontSize + 'px',
        color: t.color, opacity: t.opacity,
        zIndex: t.z,
      }"
    >{{ t.text }}</div>
  </div>
</template>

<script setup lang="ts">
import type { ResolvedLineVisual } from '@/composables/types'

defineProps<{
  visual: ResolvedLineVisual | null
}>()
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

.stage-overlay__image {
  position: absolute;
  transform: translate(-50%, -50%);
}

.stage-overlay__text {
  position: absolute;
  transform: translate(-50%, -50%);
  white-space: nowrap;
  text-align: center;
}
</style>
