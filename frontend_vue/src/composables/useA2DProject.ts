import { strFromU8, strToU8, unzip, zip, type Unzipped, type Zippable } from 'fflate'
import { buildExportEnvelope, importSession, validateEnvelope, type ExportEnvelope, type ImportResult } from './useA2DSaveLoad'
import { useScriptStore } from '@/stores/modules/script'

const PROJECT_FORMAT = 'a2d-studio-project'
const PROJECT_VERSION = 1
const PROJECT_MANIFEST = 'project.json'
const AUDIO_PATH_PATTERN = /^assets\/audio\/line-\d{4,}\.wav$/

interface ProjectManifest {
  format: typeof PROJECT_FORMAT
  version: typeof PROJECT_VERSION
  title: string
  exportedAt: string
  envelope: ExportEnvelope
}

function zipAsync(files: Zippable): Promise<Uint8Array> {
  return new Promise((resolve, reject) => {
    zip(files, { level: 6 }, (error, archive) => {
      if (error) reject(error)
      else resolve(archive)
    })
  })
}

function unzipAsync(bytes: Uint8Array): Promise<Unzipped> {
  return new Promise((resolve, reject) => {
    unzip(bytes, (error, files) => {
      if (error) reject(error)
      else resolve(files)
    })
  })
}

function safeTitle(title: string): string {
  return title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || 'a2d-project'
}

function resolveLocalAudioUrl(audioPath: string): string {
  if (audioPath.startsWith('blob:') || audioPath.startsWith('data:')) return audioPath
  if (audioPath.startsWith('/')) {
    return `http://${window.location.hostname}:8765${audioPath}`
  }
  const parsedUrl = new URL(audioPath)
  if (parsedUrl.hostname !== window.location.hostname || parsedUrl.port !== '8765') {
    throw new Error('项目只会打包本机生成的语音文件')
  }
  return parsedUrl.href
}

async function fetchLocalAudio(audioPath: string): Promise<Uint8Array> {
  const response = await fetch(resolveLocalAudioUrl(audioPath))
  if (!response.ok) throw new Error(`读取本机语音失败（HTTP ${response.status}）`)
  return new Uint8Array(await response.arrayBuffer())
}

export async function packA2DProject(
  sourceEnvelope: ExportEnvelope,
  title: string,
): Promise<Uint8Array> {
  const envelope = JSON.parse(JSON.stringify(sourceEnvelope)) as ExportEnvelope
  const entries: Zippable = {}
  const projectTitle = title.trim() || '未命名剧本'
  envelope.script.projectName = projectTitle

  for (const [index, line] of envelope.script.lines.entries()) {
    if (!line.audio_path) continue
    const archivePath = `assets/audio/line-${String(index + 1).padStart(4, '0')}.wav`
    entries[archivePath] = await fetchLocalAudio(line.audio_path)
    line.audio_path = archivePath
  }

  const manifest: ProjectManifest = {
    format: PROJECT_FORMAT,
    version: PROJECT_VERSION,
    title: projectTitle,
    exportedAt: new Date().toISOString(),
    envelope,
  }
  entries[PROJECT_MANIFEST] = strToU8(JSON.stringify(manifest, null, 2))
  return zipAsync(entries)
}

function parseProjectManifest(files: Unzipped): ProjectManifest | ImportResult {
  const projectJson = files[PROJECT_MANIFEST]
  if (!projectJson) return { ok: false, error: '项目包缺少 project.json' }

  let manifest: ProjectManifest
  try {
    manifest = JSON.parse(strFromU8(projectJson)) as ProjectManifest
  } catch {
    return { ok: false, error: '项目清单不是有效 JSON' }
  }
  if (manifest.format !== PROJECT_FORMAT || manifest.version !== PROJECT_VERSION) {
    return { ok: false, error: '不支持的 A2D 项目格式' }
  }
  const check = validateEnvelope(manifest.envelope)
  if (!check.ok) return check
  return manifest
}

export async function unpackA2DProject(file: File): Promise<ImportResult> {
  let files: Unzipped
  try {
    files = await unzipAsync(new Uint8Array(await file.arrayBuffer()))
  } catch {
    return { ok: false, error: '项目压缩包损坏或无法读取' }
  }

  const manifest = parseProjectManifest(files)
  if ('ok' in manifest) return manifest

  const envelope = manifest.envelope
  envelope.script.projectName = manifest.title
  const objectUrls: string[] = []
  for (const [index, line] of envelope.script.lines.entries()) {
    if (!line.audio_path) continue
    if (!AUDIO_PATH_PATTERN.test(line.audio_path)) {
      objectUrls.forEach((url) => URL.revokeObjectURL(url))
      return { ok: false, error: `第 ${index + 1} 句的语音引用不是项目内相对路径` }
    }
    const audioBytes = files[line.audio_path]
    if (!audioBytes) {
      objectUrls.forEach((url) => URL.revokeObjectURL(url))
      return { ok: false, error: `项目包缺少第 ${index + 1} 句的语音文件` }
    }
    const audioBuffer = new ArrayBuffer(audioBytes.byteLength)
    new Uint8Array(audioBuffer).set(audioBytes)
    const objectUrl = URL.createObjectURL(new Blob([audioBuffer], { type: 'audio/wav' }))
    objectUrls.push(objectUrl)
    line.audio_path = objectUrl
  }

  const result = await importSession(new File([JSON.stringify(envelope)], 'project.a2d.json', {
    type: 'application/json',
  }))
  if (!result.ok) objectUrls.forEach((url) => URL.revokeObjectURL(url))
  return result
}

export async function exportA2DProject(): Promise<void> {
  const script = useScriptStore()
  const archive = await packA2DProject(buildExportEnvelope(), script.projectName)
  const archiveBuffer = new ArrayBuffer(archive.byteLength)
  new Uint8Array(archiveBuffer).set(archive)
  const blob = new Blob([archiveBuffer], { type: 'application/zip' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${safeTitle(script.projectName)}.a2d.zip`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function importA2DProject(file: File): Promise<ImportResult> {
  const result = await unpackA2DProject(file)
  if (result.ok) useScriptStore().setActiveTab('script')
  return result
}
