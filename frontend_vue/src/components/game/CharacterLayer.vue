<template>
  <div class="a2d-character-layer">
    <div
      v-for="char in characters"
      :key="char.id"
      :class="[
        'a2d-char-sprite',
        char.id === speaker ? 'a2d-is-speaking' : 'a2d-is-dimmed',
      ]"
      :style="spriteStyle(char)"
      @pointerdown.prevent="startDrag($event, char.id)"
    >
      <img
        :src="char.avatarUrl"
        :alt="char.name"
        class="char-image"
        draggable="false"
      />
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'

export interface CharSprite {
  id: string       // "ema" | "hiro"
  name: string     // display name
  avatarUrl: string // avatar image path
  x: number
  y: number
  scale: number
}

const props = defineProps<{
  characters: CharSprite[]
  speaker: string | null
}>()

const emit = defineEmits<{
  positionChange: [id: string, x: number, y: number]
}>()

const dragging = ref<string | null>(null)
const dragStart = ref({ x: 0, y: 0, originX: 0, originY: 0 })

function spriteStyle(char: CharSprite) {
  return {
    left: `calc(50% + ${char.x}px)`,
    top: `calc(30% + ${char.y}px)`,
    transform: `translate(-50%, -50%) scale(${char.scale})`,
    cursor: dragging.value === char.id ? 'grabbing' : 'grab',
    userSelect: 'none' as const,
  }
}

function startDrag(event: PointerEvent, id: string) {
  const char = props.characters.find(c => c.id === id)
  if (!char) return
  dragging.value = id
  dragStart.value = {
    x: event.clientX,
    y: event.clientY,
    originX: char.x,
    originY: char.y,
  }

  const onMove = (e: PointerEvent) => {
    if (dragging.value !== id) return
    const dx = e.clientX - dragStart.value.x
    const dy = e.clientY - dragStart.value.y
    emit('positionChange', id, dragStart.value.originX + dx, dragStart.value.originY + dy)
  }
  const onUp = () => {
    dragging.value = null
    window.removeEventListener('pointermove', onMove)
    window.removeEventListener('pointerup', onUp)
  }
  window.addEventListener('pointermove', onMove)
  window.addEventListener('pointerup', onUp)
}
</script>

<style scoped>
@import '@/assets/a2d-character.css';

.a2d-character-layer {
  position: absolute;
  inset: 0;
  pointer-events: none;
  z-index: 10;
}

.a2d-char-sprite {
  position: absolute;
  pointer-events: auto;
  transition: filter 0.3s ease, transform 0.3s ease;
}

.char-image {
  max-height: 65vh;
  width: auto;
  object-fit: contain;
  object-position: center bottom;
}
</style>
