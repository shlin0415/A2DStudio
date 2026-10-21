<template>
  <section class="script-editor" data-testid="script-editor">
    <header class="script-editor__header">
      <div>
        <label class="script-editor__title">
          项目名
          <input
            aria-label="项目名称"
            :value="store.projectName"
            @input="store.setProjectName(($event.target as HTMLInputElement).value)"
          />
        </label>
        <span>{{ store.lines.length }} 句</span>
      </div>
      <div class="script-editor__add-actions">
        <button type="button" data-testid="export-project" @click="exportProject">
          导出项目包
        </button>
        <button type="button" data-testid="open-project" @click="triggerProjectImport">
          打开项目包
        </button>
        <button type="button" data-testid="save-project-folder" @click="saveProjectFolder">
          保存到项目文件夹
        </button>
        <button type="button" data-testid="open-project-folder" @click="openProjectFolder">
          打开项目文件夹
        </button>
        <button type="button" data-testid="add-ema-line" @click="store.createManualLine('ema')">
          ＋ 添加艾玛台词
        </button>
        <button type="button" data-testid="add-hiro-line" @click="store.createManualLine('hiro')">
          ＋ 添加希罗台词
        </button>
      </div>
    </header>
    <input
      ref="projectInput"
      data-testid="project-input"
      type="file"
      accept=".a2d.zip,application/zip"
      hidden
      @change="importProject"
    />
    <p v-if="projectMessage" :class="['script-editor__message', { error: projectError }]" role="status">
      {{ projectMessage }}
    </p>

    <p v-if="store.lines.length === 0" class="script-editor__empty">
      先添加一句台词，再选择说话人并合成语音。这里不需要连接 LLM。
    </p>
    <p v-if="store.error" class="script-editor__error" role="status">
      {{ store.error.message }}
    </p>

    <div v-if="store.lines.length > 0" class="script-editor__workspace">
      <ol class="script-editor__lines" aria-label="剧本台词列表">
        <li v-for="line in store.lines" :key="line.id">
          <button
            type="button"
            :class="['script-editor__line', { 'script-editor__line--selected': activeLine?.id === line.id }]"
            :data-testid="`select-line-${line.id}`"
            @click="store.selectLine(line.id)"
          >
            <span>{{ line.index + 1 }}</span>
            <span>{{ speakerLabel(line.speaker) }}</span>
            <span>{{ line.display_text || '（空台词）' }}</span>
            <span>{{ line.audio_path ? '已合成' : '未合成' }}</span>
          </button>
        </li>
      </ol>

      <div v-if="activeLine" class="script-editor__details">
        <div class="script-editor__row">
          <label>
            说话人
            <select
              :aria-label="`第 ${activeLine.index + 1} 句说话人`"
              :value="activeLine.speaker"
              @change="updateSpeaker(activeLine, $event)"
            >
              <option v-for="speaker in speakerOptions" :key="speaker" :value="speaker">
                {{ speakerLabel(speaker) }}
              </option>
            </select>
          </label>
          <div class="script-editor__order-actions">
            <button
              type="button"
              :disabled="activeLine.index === 0"
              :aria-label="`第 ${activeLine.index + 1} 句上移`"
              @click="store.moveLine(activeLine.id, -1)"
            >
              上移
            </button>
            <button
              type="button"
              :disabled="activeLine.index === store.lines.length - 1"
              :aria-label="`第 ${activeLine.index + 1} 句下移`"
              @click="store.moveLine(activeLine.id, 1)"
            >
              下移
            </button>
            <button type="button" class="danger" @click="store.removeLine(activeLine.id)">
              删除
            </button>
          </div>
        </div>

        <label class="script-editor__field">
          台词文本
          <textarea
            :data-testid="`line-text-${activeLine.id}`"
            :value="activeLine.display_text"
            rows="2"
            @input="updateDisplayText(activeLine, $event)"
          />
        </label>
        <label class="script-editor__field">
          语音文本（用于合成，可与台词不同；本流程不调用在线翻译）
          <textarea
            :data-testid="`line-tts-text-${activeLine.id}`"
            :value="activeLine.tts_text"
            rows="2"
            @input="updateTtsText(activeLine, $event)"
          />
        </label>

        <div class="script-editor__footer">
          <span v-if="!isInitialized">正在读取本机语音配置…</span>
          <span v-else-if="!availableSpeakers.includes(activeLine.speaker)">该说话人没有可用的本机语音配置。</span>
          <span v-else-if="activeLine.audio_path">已有语音；修改台词或说话人后需要重新合成。</span>
          <span v-else>语音由所选说话人的本机 GSV 服务合成。</span>
          <button
            type="button"
            :data-testid="`synthesize-${activeLine.id}`"
            :disabled="!activeLine.tts_text.trim() || store.isBusy || activeLine.speaker === 'narrator' || !isInitialized || !availableSpeakers.includes(activeLine.speaker)"
            @click="synthesize(activeLine)"
          >
            合成此句语音
          </button>
        </div>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { useA2DWebSocket } from '@/composables/useA2DWebSocket'
import {
  exportA2DProject,
  importA2DProject,
  openA2DProjectFromDirectory,
  pickA2DProjectDirectory,
  saveA2DProjectToDirectory,
} from '@/composables/useA2DProject'

const store = useScriptStore()
const { sendRegenerateTTS, availableSpeakers, isInitialized } = useA2DWebSocket()
const projectInput = ref<HTMLInputElement | null>(null)
const projectMessage = ref('')
const projectError = ref(false)

const activeLine = computed(() =>
  store.lines.find((line) => line.id === store.selectedLineId) ?? store.lines[0] ?? null,
)
const speakerOptions = computed(() => {
  const speakers = new Set(availableSpeakers.value)
  if (activeLine.value?.speaker) speakers.add(activeLine.value.speaker)
  return [...speakers]
})

function speakerLabel(speaker: string): string {
  if (speaker === 'ema') return '艾玛 (GSV1)'
  if (speaker === 'hiro') return '希罗 (GSV2)'
  if (speaker === 'narrator') return '旁白'
  return speaker
}

function updateSpeaker(line: ScriptLine, event: Event): void {
  const speaker = (event.target as HTMLSelectElement).value
  store.updateLine(line.id, { speaker })
}

function updateDisplayText(line: ScriptLine, event: Event): void {
  const displayText = (event.target as HTMLTextAreaElement).value
  const updates: Pick<ScriptLine, 'display_text'> & Partial<Pick<ScriptLine, 'tts_text'>> = {
    display_text: displayText,
  }
  if (!line.tts_text || line.tts_text === line.display_text) updates.tts_text = displayText
  store.updateLine(line.id, updates)
}

function updateTtsText(line: ScriptLine, event: Event): void {
  store.updateLine(line.id, { tts_text: (event.target as HTMLTextAreaElement).value })
}

function synthesize(line: ScriptLine): void {
  store.clearError()
  sendRegenerateTTS(line.id, line.tts_text, line.speaker, false)
}

async function exportProject(): Promise<void> {
  projectMessage.value = ''
  projectError.value = false
  try {
    await exportA2DProject()
    projectMessage.value = '项目包已导出'
  } catch (error) {
    projectError.value = true
    projectMessage.value = error instanceof Error ? error.message : '项目包导出失败'
  }
}

function showDirectoryActionError(error: unknown): void {
  if (error instanceof DOMException && error.name === 'AbortError') {
    projectMessage.value = '已取消文件夹选择'
    projectError.value = false
    return
  }
  projectError.value = true
  projectMessage.value = error instanceof Error ? error.message : '项目文件夹操作失败'
}

async function saveProjectFolder(): Promise<void> {
  projectMessage.value = ''
  projectError.value = false
  try {
    const directory = await pickA2DProjectDirectory('readwrite')
    await saveA2DProjectToDirectory(directory)
    projectMessage.value = '项目文件夹已保存'
  } catch (error) {
    showDirectoryActionError(error)
  }
}

async function openProjectFolder(): Promise<void> {
  projectMessage.value = ''
  projectError.value = false
  try {
    const directory = await pickA2DProjectDirectory('read')
    const result = await openA2DProjectFromDirectory(directory)
    projectError.value = !result.ok
    projectMessage.value = result.ok
      ? `项目已打开（${store.lines.length} 句）`
      : result.error || '项目文件夹打开失败'
  } catch (error) {
    showDirectoryActionError(error)
  }
}

function triggerProjectImport(): void {
  projectMessage.value = ''
  projectError.value = false
  projectInput.value?.click()
}

async function importProject(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement
  const file = input.files?.[0]
  if (!file) return
  const result = await importA2DProject(file)
  projectError.value = !result.ok
  projectMessage.value = result.ok
    ? `项目已打开（${store.lines.length} 句）`
    : result.error || '项目打开失败'
  input.value = ''
}
</script>

<style scoped>
.script-editor {
  max-height: 38vh;
  overflow: auto;
  padding: 12px 16px;
  background: rgba(20, 20, 30, 0.96);
  color: #f5f6fa;
}

.script-editor__header,
.script-editor__header > div,
.script-editor__add-actions,
.script-editor__row,
.script-editor__order-actions,
.script-editor__footer {
  display: flex;
  align-items: center;
  gap: 8px;
}

.script-editor__add-actions { flex-wrap: wrap; }

.script-editor__header,
.script-editor__row,
.script-editor__footer {
  justify-content: space-between;
}

.script-editor__header > div:first-child { gap: 10px; }
.script-editor__title { display: flex; align-items: center; gap: 6px; font-size: 12px; }
.script-editor__title input { width: 160px; }
.script-editor__message { margin: 8px 0 0; color: #b8e7bd; }
.script-editor__message.error { color: #ffaaa5; }
.script-editor__header span,
.script-editor__empty,
.script-editor__footer span { color: rgba(245, 246, 250, 0.62); }
.script-editor__empty { margin: 12px 0 2px; }
.script-editor__error { color: #ffaaa5; }

.script-editor button,
.script-editor select,
.script-editor textarea {
  border: 1px solid rgba(255, 255, 255, 0.2);
  border-radius: 5px;
  padding: 7px 9px;
  background: rgba(255, 255, 255, 0.06);
  color: inherit;
}

.script-editor button { cursor: pointer; }
.script-editor button:disabled { cursor: not-allowed; opacity: 0.45; }
.script-editor .danger { color: #ffaaa5; }

.script-editor__workspace {
  display: grid;
  grid-template-columns: minmax(180px, 32%) 1fr;
  gap: 12px;
  margin-top: 12px;
}

.script-editor__lines {
  display: flex;
  flex-direction: column;
  gap: 4px;
  max-height: 250px;
  overflow: auto;
  margin: 0;
  padding: 0;
  list-style: none;
}

.script-editor__line {
  display: grid;
  grid-template-columns: 24px 46px minmax(0, 1fr) 54px;
  width: 100%;
  text-align: left;
  gap: 6px;
}

.script-editor__line span:nth-child(3) {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.script-editor__line span:last-child { font-size: 11px; color: rgba(245, 246, 250, 0.55); }
.script-editor__line--selected { border-color: #4a90d9 !important; background: rgba(74, 144, 217, 0.2) !important; }
.script-editor__details { display: flex; flex-direction: column; gap: 8px; min-width: 0; }
.script-editor__row label { display: flex; align-items: center; gap: 8px; }
.script-editor__field { display: flex; flex-direction: column; gap: 4px; }
.script-editor__field textarea { resize: vertical; width: 100%; font: inherit; }
.script-editor__footer span { font-size: 12px; }

@media (max-width: 700px) {
  .script-editor { max-height: 48vh; }
  .script-editor__workspace { grid-template-columns: 1fr; }
  .script-editor__lines { max-height: 110px; }
  .script-editor__footer { align-items: flex-start; flex-direction: column; }
}
</style>
