<template>
  <div v-if="currentLine" class="a2d-dialog-layer">
    <div class="dialog-speaker-label">
      {{ speakerName }}
    </div>
    <div class="dialog-text-bubble">
      {{ currentLine.display_text }}
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import type { ScriptLine } from '@/stores/modules/script'
import type { CharSprite } from './CharacterLayer.vue'

const props = defineProps<{
  currentLine: ScriptLine | null
  characters: CharSprite[]
}>()

const speakerName = computed(() => {
  if (!props.currentLine) return ''
  const char = props.characters.find(c => c.id === props.currentLine!.speaker)
  return char?.name ?? props.currentLine.speaker
})
</script>

<style scoped>
.a2d-dialog-layer {
  position: absolute;
  bottom: 280px;
  left: 50%;
  transform: translateX(-50%);
  z-index: 20;
  text-align: center;
  pointer-events: none;
}

.dialog-speaker-label {
  color: rgba(255, 255, 255, 0.85);
  font-size: 14px;
  margin-bottom: 8px;
  font-weight: 600;
  text-shadow: 0 1px 4px rgba(0, 0, 0, 0.8);
}

.dialog-text-bubble {
  background: rgba(0, 0, 0, 0.78);
  color: #fff;
  padding: 14px 28px;
  border-radius: 14px;
  font-size: 18px;
  max-width: 620px;
  line-height: 1.65;
  text-shadow: 0 1px 2px rgba(0, 0, 0, 0.5);
  box-shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
}
</style>
