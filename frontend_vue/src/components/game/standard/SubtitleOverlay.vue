<!--
  SubtitleOverlay — displays the current line's display_text synced to replay.
  Mounted in StageView above character and project visual overlays.
  Reads subtitle text from the replay engine (useA2DReplay.currentSubtitle).
-->
<template>
  <div v-if="text" class="subtitle-overlay">
    <div
      class="subtitle-overlay__text"
      :class="{ 'subtitle-overlay__text--narrator': isNarrator }"
    >
      {{ text }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { watch } from 'vue'
import { emitTrace } from '@/utils/a2d-trace'

const props = withDefaults(defineProps<{
  text: string
  isNarrator?: boolean
  lineId?: string | null
  lineIndex?: number | null
}>(), {
  lineId: null,
  lineIndex: null,
})

watch(
  () => [props.lineId, props.text] as const,
  ([lineId, text], previousValue) => {
    const [previousLineId, previousText] = previousValue ?? [null, '']
    if (previousLineId && previousText) {
      emitTrace('subtitle_hide', { lineId: previousLineId })
    }
    if (!lineId || !text) return

    emitTrace('subtitle_show', {
      lineId,
      ...(props.lineIndex === null ? {} : { lineIndex: props.lineIndex }),
      characterCount: text.length,
    })
  },
  { immediate: true },
)
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

.subtitle-overlay__text--narrator {
  background: transparent;
  color: #d0d0d0;
  text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
  font-style: italic;
}
</style>
