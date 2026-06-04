<template>
  <div class="review-panel">
    <!-- Thinking / Synthesizing -->
    <div v-if="store.isThinking" class="status-row">
      <span class="status-text">{{ currentSpeakerName }}正在思考...</span>
    </div>
    <div v-else-if="store.isSynthesizing" class="status-row">
      <span class="status-text">&#x1F50A; 语音合成中...</span>
    </div>

    <!-- Paused — edit + continue -->
    <div v-else-if="store.isPaused && store.currentLine" class="edit-area">
      <div class="edit-row">
        <button class="btn-icon" @click="replayAudio" title="播放">&#x25B6;</button>
        <textarea
          v-model="editingText"
          class="text-editor"
          rows="2"
        ></textarea>
      </div>
      <div class="action-row">
        <button class="btn-secondary" @click="regenerateTTS">
          &#x267B; 重生成语音
        </button>
        <button class="btn-primary" @click="handleContinue">
          &#x2192; 继续
        </button>
      </div>
    </div>

    <!-- Error -->
    <div v-else-if="store.hasError && store.error" class="error-area">
      <div class="error-header">&#x26A0;&#xFE0F; {{ errorLabel }}</div>
      <div class="error-message">{{ store.error.message }}</div>
      <pre class="error-detail">{{ store.error.detail }}</pre>
      <div class="error-retry-info">
        已重试 {{ store.error.retry_count }}/{{ store.error.max_retries }}
      </div>
      <div class="action-row">
        <button
          v-if="store.error.error_type !== 'format_error' && store.error.retry_count < store.error.max_retries"
          class="btn-primary"
          @click="retry"
        >
          手动重试
        </button>
        <button
          v-if="store.error.error_type === 'tts_error'"
          class="btn-secondary"
          @click="skipTTS"
        >
          跳过语音
        </button>
      </div>
    </div>

    <!-- Idle -->
    <div v-else class="status-row">
      <button class="btn-primary btn-large" @click="handleStart">
        开始对话
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, computed } from 'vue'
import { useScriptStore } from '@/stores/modules/script'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'

const store = useScriptStore()
const { sendStart, sendContinue, sendRetry, sendRegenerateTTS } = useA2DWebSocket()

const editingText = ref('')

watch(() => store.currentLine, (line) => {
  if (line) editingText.value = line.display_text
})

const currentSpeakerName = computed(() => {
  const lastLine = store.lines[store.lines.length - 1]
  if (!lastLine) return ''
  return lastLine.speaker === 'ema' ? '桜羽エマ' : '希罗'
})

const errorLabel = computed(() => {
  const labels: Record<string, string> = {
    llm_timeout: 'AI 响应超时',
    llm_api_error: 'AI 服务异常',
    format_error: 'AI 输出格式异常',
    tts_error: '语音合成失败',
    network_error: '网络连接中断',
    unknown: '未知错误',
  }
  return labels[store.error?.error_type || 'unknown'] || '错误'
})

function replayAudio() {
  store.setPhase('paused')
}

function handleStart() {
  store.reset()
  sendStart()
}

function handleContinue() {
  if (!store.currentLine) return
  const edits = editingText.value !== store.currentLine.display_text
    ? [{ id: store.currentLine.id, text: editingText.value }]
    : []
  sendContinue(edits)
}

function regenerateTTS() {
  if (!store.currentLine) return
  sendRegenerateTTS(store.currentLine.id, editingText.value)
}

function retry() {
  store.clearError()
  sendRetry()
}

function skipTTS() {
  store.setPhase('paused')
}
</script>

<style scoped>
.review-panel {
  background: rgba(20, 20, 30, 0.95);
  padding: 16px 24px;
  color: #fff;
}

.status-row {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 60px;
}

.status-text {
  font-size: 16px;
  color: rgba(255, 255, 255, 0.8);
}

.edit-area {
  width: 100%;
}

.edit-row {
  display: flex;
  gap: 12px;
  align-items: flex-start;
}

.text-editor {
  flex: 1;
  background: rgba(255, 255, 255, 0.1);
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 8px;
  color: #fff;
  padding: 8px 12px;
  font-size: 16px;
  resize: none;
  font-family: inherit;
  line-height: 1.5;
}

.text-editor:focus {
  outline: none;
  border-color: #4a90d9;
}

.action-row {
  display: flex;
  gap: 12px;
  justify-content: flex-end;
  margin-top: 12px;
}

.btn-primary {
  background: #4a90d9;
  color: #fff;
  border: none;
  padding: 8px 20px;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-primary:hover { background: #3a7bc8; }

.btn-secondary {
  background: rgba(255, 255, 255, 0.1);
  color: #ccc;
  border: 1px solid rgba(255, 255, 255, 0.2);
  padding: 8px 20px;
  border-radius: 6px;
  font-size: 15px;
  cursor: pointer;
  transition: background 0.2s;
}
.btn-secondary:hover { background: rgba(255, 255, 255, 0.2); }

.btn-icon {
  background: none;
  border: 1px solid rgba(255, 255, 255, 0.3);
  color: #fff;
  width: 40px;
  height: 40px;
  border-radius: 50%;
  font-size: 16px;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.btn-large {
  padding: 12px 36px;
  font-size: 18px;
}

.error-area {
  padding: 8px 0;
}

.error-header {
  font-size: 16px;
  color: #ff6b6b;
  margin-bottom: 6px;
}

.error-message {
  font-size: 14px;
  color: #ccc;
  margin-bottom: 8px;
}

.error-detail {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 4px;
  padding: 8px;
  font-size: 12px;
  max-height: 120px;
  overflow-y: auto;
  white-space: pre-wrap;
  color: #999;
}

.error-retry-info {
  font-size: 12px;
  color: #888;
  margin-top: 8px;
}
</style>
