<template>
  <div class="stage-view">
    <!-- LingChat standard: background + multi-character stage + dialog -->
    <GameBackground />
    <GameRolesStage
      ref="gameAvatarRef"
      @audio-ended="handleAudioFinished"
      @audio-started="handleAudioStarted"
    />
    <GameDialog ref="gameDialogRef" />

    <!-- A2D overlay: script editor panel at bottom -->
    <ScriptPanel />
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { GameBackground, GameRolesStage, GameDialog } from '@/components/game/standard'
import ScriptPanel from '@/components/game/ScriptPanel.vue'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'
import { useUIStore } from '@/stores/modules/ui/ui'

const uiStore = useUIStore()

// ── WS lifecycle ──────────────────────────────────────
const { sendStart, sendContinue, sendRetry, sendRegenerateTTS } =
  useA2DWebSocket()

// ── Audio / dialog refs (for future auto-advance) ─────
const gameAvatarRef = ref<InstanceType<typeof GameRolesStage> | null>(null)
const gameDialogRef = ref<InstanceType<typeof GameDialog> | null>(null)

const handleAudioStarted = () => {
  // placeholder: audio playback tracking
}

const handleAudioFinished = () => {
  // placeholder: trigger auto-advance in auto mode
}
</script>

<style scoped>
.stage-view {
  position: absolute;
  height: 100%;
  width: 100%;
  display: flex;
  flex-direction: column;
  justify-content: flex-end;
  align-items: center;
  overflow: hidden;
}
</style>
