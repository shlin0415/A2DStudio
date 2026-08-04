<!--
  SubtitleOverlay — displays the current line's display_text synced to replay.
  Mounted in StageView above GameRolesStage, below GameDialog.
  Reads subtitle text from the replay engine (useA2DReplay.currentSubtitle).
-->
<template>
  <div v-if="text" class="subtitle-overlay">
    <div class="subtitle-overlay__text">{{ text }}</div>
  </div>
</template>

<script setup lang="ts">
defineProps<{
  text: string
}>()
</script>

<style scoped>
.subtitle-overlay {
  position: absolute;
  bottom: 12%;
  left: 50%;
  transform: translateX(-50%);
  z-index: 12;
  pointer-events: none;
  max-width: 80%;
}

.subtitle-overlay__text {
  background: rgba(0, 0, 0, 0.6);
  color: #fff;
  padding: 8px 16px;
  border-radius: 8px;
  font-size: 18px;
  text-align: center;
  white-space: pre-wrap;
}
</style>
