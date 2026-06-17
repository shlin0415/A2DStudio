<template>
  <div class="review-panel">
    <!-- Thinking / Synthesizing — show generated text as read-only preview -->
    <div v-if="(store.isThinking || store.isSynthesizing) && store.currentLine" class="preview-area">
      <div class="preview-text">{{ store.currentLine.display_text }}</div>
      <div class="preview-status">
        <template v-if="store.isThinking">思考中...</template>
        <template v-else>&#x1F50A; 语音合成中...</template>
      </div>
    </div>

    <!-- Thinking / Synthesizing — no text yet -->
    <div v-else-if="store.isThinking" class="status-row">
      <span class="status-text">思考中...</span>
    </div>
    <div v-else-if="store.isTranslating" class="status-row">
      <span class="status-text">&#x1F310; 翻译中...</span>
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
          @input="onTextEdited"
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
let lastLineId = ''
let userEdited = false

// The line currently displayed in the editor:
// selectedLine (from EventTrack click) takes priority over currentLine (latest generated)
const activeLine = computed(() => store.selectedLine || store.currentLine)

// Watch for line changes: new generation OR user clicking a timeline line
watch(activeLine, (line) => {
  if (!line) return
  // Check store-level editedText first (persisted across tab switches)
  const stored = store.editedText[line.id]
  if (stored !== undefined) {
    editingText.value = stored
    lastLineId = line.id
    userEdited = true
    return
  }
  // New line arrived (different id): reset editing text + dirty flag
  if (line.id !== lastLineId) {
    lastLineId = line.id
    editingText.value = line.display_text
    userEdited = false
  }
  // Same line, user hasn't edited: update from store
  else if (!userEdited) {
    editingText.value = line.display_text
  }
})

function onTextEdited() {
  userEdited = true
  // Persist to store-level editedText map for cross-tab survival
  const line = activeLine.value
  if (line) {
    store.setEdited(line.id, editingText.value)
  }
}

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
  const line = activeLine.value
  if (!line) return
  const originalText = line.display_text
  const edits = editingText.value !== originalText
    ? [{ id: line.id, text: editingText.value }]
    : []
  // Persist current edit before sending
  if (userEdited) {
    store.setEdited(line.id, editingText.value)
  }
  sendContinue(edits)
  // Clear store-level edit for this line after commit
  store.clearEdited(line.id)
}

function regenerateTTS() {
  const line = activeLine.value
  if (!line) return
  sendRegenerateTTS(line.id, editingText.value)
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

.preview-area {
  padding: 8px 0;
}

.preview-text {
  background: rgba(255, 255, 255, 0.05);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  padding: 10px 14px;
  font-size: 16px;
  line-height: 1.6;
  color: #eee;
  margin-bottom: 8px;
  white-space: pre-wrap;
  word-break: break-word;
}

.preview-status {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.45);
  padding-left: 4px;
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
