<template>
  <div class="stage-canvas">
    <CharacterLayer
      :characters="sprites"
      :speaker="currentSpeaker"
      @position-change="handlePositionChange"
    />
    <DialogLayer
      :current-line="store.currentLine"
      :characters="sprites"
    />
    <ScriptPanel />
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { useScriptStore } from '@/stores/modules/script'
import CharacterLayer from './CharacterLayer.vue'
import type { CharSprite } from './CharacterLayer.vue'
import DialogLayer from './DialogLayer.vue'
import ScriptPanel from './ScriptPanel.vue'

const store = useScriptStore()

const sprites = ref<CharSprite[]>([
  {
    id: 'ema',
    name: '桜羽エマ',
    avatarUrl: '/api/v1/chat/character/get_avatar/1/正常/default',
    x: -180,
    y: 0,
    scale: 1.0,
  },
  {
    id: 'hiro',
    name: '希羅',
    avatarUrl: '/api/v1/chat/character/get_avatar/2/正常/default',
    x: 180,
    y: 0,
    scale: 1.0,
  },
])

const currentSpeaker = computed(() => store.currentLine?.speaker ?? null)

function handlePositionChange(id: string, x: number, y: number) {
  const char = sprites.value.find(c => c.id === id)
  if (char) {
    char.x = x
    char.y = y
  }
}
</script>

<style scoped>
.stage-canvas {
  position: relative;
  width: 100vw;
  height: 100vh;
  overflow: hidden;
  background: radial-gradient(ellipse at center, #1a1a2e 0%, #0a0a15 100%);
}
</style>
