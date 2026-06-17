<template>
  <div class="event-track">
    <div v-if="store.lines.length === 0" class="empty-state">
      暂无台词。开始对话后，生成的所有台词将显示在这里。
    </div>
    <div v-else ref="trackRef" class="line-list">
      <div
        v-for="line in store.lines"
        :key="line.id"
        :class="[
          'line-item',
          { 'line-item--active': store.selectedLineId === line.id }
        ]"
        @click="store.selectLine(line.id)"
      >
        <span class="line-index">{{ line.index + 1 }}</span>
        <span :class="['line-speaker', line.speaker]">
          {{ line.speaker === 'ema' ? 'エマ' : line.speaker === 'hiro' ? '希羅' : line.speaker }}
        </span>
        <span class="line-text">{{ line.display_text }}</span>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import { useScriptStore } from '@/stores/modules/script'

const store = useScriptStore()
const trackRef = ref<HTMLElement | null>(null)

// Auto-scroll to bottom when new lines arrive (only if user is near bottom)
watch(() => store.lines.length, () => {
  nextTick(() => {
    if (!trackRef.value) return
    const el = trackRef.value
    const isNearBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 60
    if (isNearBottom) {
      el.scrollTop = el.scrollHeight
    }
  })
})
</script>

<style scoped>
.event-track {
  background: rgba(20, 20, 30, 0.95);
  padding: 12px 16px;
  max-height: 200px;
  overflow-y: auto;
}

.empty-state {
  color: rgba(255, 255, 255, 0.3);
  text-align: center;
  padding: 24px;
  font-size: 14px;
}

.line-list {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.line-item {
  display: flex;
  gap: 10px;
  align-items: baseline;
  padding: 4px 8px;
  border-radius: 4px;
  font-size: 14px;
  cursor: default;
}

.line-item:hover {
  background: rgba(255, 255, 255, 0.05);
}

.line-item--active {
  background: rgba(74, 144, 217, 0.2);
  border-left: 3px solid #4a90d9;
  padding-left: 5px;
}

.line-index {
  color: rgba(255, 255, 255, 0.3);
  font-size: 12px;
  min-width: 24px;
}

.line-speaker {
  font-weight: 600;
  min-width: 44px;
}

.line-speaker.ema { color: #f4a7b9; }
.line-speaker.hiro { color: #7ec8e3; }

.line-text {
  color: rgba(255, 255, 255, 0.85);
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
