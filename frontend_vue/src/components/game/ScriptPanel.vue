<template>
  <div class="script-panel">
    <div class="panel-tabs">
      <button
        :class="['tab', { active: store.activeTab === 'review' }]"
        @click="store.activeTab = 'review'"
      >
        审核台
      </button>
      <button
        :class="['tab', { active: store.activeTab === 'event' }]"
        @click="store.activeTab = 'event'"
      >
        时轴
      </button>
    </div>
    <div class="panel-content">
      <KeepAlive>
        <ReviewPanel v-if="store.activeTab === 'review'" />
        <EventTrack v-else />
      </KeepAlive>
    </div>
  </div>
</template>

<script setup lang="ts">
import ReviewPanel from './ReviewPanel.vue'
import EventTrack from './EventTrack.vue'
import { useScriptStore } from '@/stores/modules/script'

const store = useScriptStore()
</script>

<style scoped>
.script-panel {
  position: absolute;
  bottom: 0;
  left: 0;
  right: 0;
  z-index: 30;
}

.panel-tabs {
  display: flex;
  background: rgba(10, 10, 20, 0.95);
  border-bottom: 1px solid rgba(255, 255, 255, 0.08);
}

.tab {
  padding: 10px 24px;
  background: none;
  border: none;
  color: rgba(255, 255, 255, 0.5);
  font-size: 14px;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all 0.2s;
}

.tab:hover {
  color: rgba(255, 255, 255, 0.8);
}

.tab.active {
  color: #4a90d9;
  border-bottom-color: #4a90d9;
}

.panel-content {
  min-height: 100px;
}
</style>
