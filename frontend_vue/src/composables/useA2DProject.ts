import { strToU8 } from 'fflate'
import { useGameStore } from '@/stores/modules/game'
import { useScriptStore, type ImageOverlay, type LineOverlay, type ScriptLine, type TextOverlay } from '@/stores/modules/script'
import {
  A2D_PROJECT_FORMAT,
  A2D_PROJECT_MAX_ARCHIVE_BYTES,
  A2D_PROJECT_MAX_ENTRY_BYTES,
  A2D_PROJECT_MAX_EXPANDED_BYTES,
  A2D_PROJECT_MAX_MANIFEST_BYTES,
  A2D_PROJECT_SCHEMA_VERSION,
  nextProjectByteCount,
  validateProjectManifest,
  type A2DProjectLine,
  type A2DProjectManifest,
  type A2DProjectRole,
} from './a2d-project-format'
import { readProjectArchive, writeProjectArchive } from './a2d-project-archive'
import { packA2DProject } from './a2d-project-export'
import { registerImportedProjectAssets, getProjectAvatarRegistryKey } from './a2d-project-runtime-assets'
import { buildExportEnvelope, importSession, type ExportEnvelope, type ImportResult } from './useA2DSaveLoad'

const DOWNLOAD_URL_REVOKE_DELAY_MS = 1000
const PROJECT_RUNTIME_ROLE_ID_START = -1_000_000

interface A2DDirectoryPickerWindow extends Window {
  showDirectoryPicker?: (options?: { mode: 'read' | 'readwrite' }) => Promise<FileSystemDirectoryHandle>
}

function safeTitle(title: string): string {
  return title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || 'a2d-project'
}

export { packA2DProject }

function copyBytesToArrayBuffer(bytes: Uint8Array): ArrayBuffer {
  const copy = new Uint8Array(bytes.byteLength)
  copy.set(bytes)
  return copy.buffer
}

function isNotFoundError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'NotFoundError'
}

async function getDirectoryFileHandle(
  directory: FileSystemDirectoryHandle,
  path: string,
  create: boolean,
): Promise<FileSystemFileHandle> {
  const parts = path.split('/')
  let currentDirectory = directory
  for (const part of parts.slice(0, -1)) {
    currentDirectory = await currentDirectory.getDirectoryHandle(part, { create })
  }
  return currentDirectory.getFileHandle(parts[parts.length - 1]!, { create })
}

async function readDirectoryFile(directory: FileSystemDirectoryHandle, path: string): Promise<File> {
  try {
    return await (await getDirectoryFileHandle(directory, path, false)).getFile()
  } catch (error) {
    if (isNotFoundError(error)) throw new Error(`项目文件夹缺少文件：${path}`)
    throw error
  }
}

async function writeDirectoryFile(directory: FileSystemDirectoryHandle, path: string, bytes: Uint8Array): Promise<void> {
  const fileHandle = await getDirectoryFileHandle(directory, path, true)
  const writable = await fileHandle.createWritable()
  try {
    await writable.write(copyBytesToArrayBuffer(bytes))
    await writable.close()
  } catch (error) {
    await writable.abort().catch(() => undefined)
    throw error
  }
}

async function hasExistingProjectManifest(directory: FileSystemDirectoryHandle): Promise<A2DProjectManifest | null> {
  let manifestFile: File
  try {
    manifestFile = await (await directory.getFileHandle('project.json')).getFile()
  } catch (error) {
    if (isNotFoundError(error)) return null
    throw error
  }
  if (manifestFile.size > A2D_PROJECT_MAX_MANIFEST_BYTES) throw new Error('目标文件夹的 project.json 超过 10 MiB 限制')

  let manifest: unknown
  try {
    manifest = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(await manifestFile.arrayBuffer()))
  } catch {
    throw new Error('目标文件夹已有无法识别的 project.json，已拒绝覆盖')
  }
  const validation = validateProjectManifest(manifest)
  if (!validation.ok) throw new Error('目标文件夹已有无法识别的 project.json，已拒绝覆盖')
  return manifest as A2DProjectManifest
}

async function findDirectoryFile(directory: FileSystemDirectoryHandle, path: string): Promise<File | null> {
  try {
    return await (await getDirectoryFileHandle(directory, path, false)).getFile()
  } catch (error) {
    if (isNotFoundError(error)) return null
    throw error
  }
}

interface DirectoryResourceWrite {
  path: string
  bytes: Uint8Array
}

function createUniqueResourcePath(path: string): string {
  const separator = path.lastIndexOf('/')
  const filename = path.slice(separator + 1)
  const extensionIndex = filename.lastIndexOf('.')
  const basename = extensionIndex > 0 ? filename.slice(0, extensionIndex) : filename
  const extension = extensionIndex > 0 ? filename.slice(extensionIndex) : ''
  return `${path.slice(0, separator + 1)}${basename}-${crypto.randomUUID()}${extension}`
}

async function fileMatchesBytes(file: File, expectedBytes: Uint8Array): Promise<boolean> {
  if (file.size !== expectedBytes.byteLength) return false
  const reader = file.stream().getReader()
  let offset = 0
  let matches = true
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      for (let index = 0; index < value.byteLength; index += 1) {
        if (value[index] !== expectedBytes[offset + index]) matches = false
      }
      offset += value.byteLength
    }
  } finally {
    reader.releaseLock()
  }
  return matches && offset === expectedBytes.byteLength
}

async function planDirectoryResourceWrites(
  directory: FileSystemDirectoryHandle,
  manifest: A2DProjectManifest,
  archiveFiles: Map<string, Uint8Array>,
  existingManifest: A2DProjectManifest | null,
): Promise<{ replacements: Map<string, string>; writes: DirectoryResourceWrite[] }> {
  const replacements = new Map<string, string>()
  const writes: DirectoryResourceWrite[] = []

  for (const resource of manifest.resources) {
    const originalPath = resource.path
    const bytes = archiveFiles.get(originalPath)
    if (!bytes) throw new Error(`项目包缺少资源：${originalPath}`)

    const existingFile = await findDirectoryFile(directory, originalPath)
    const previousResource = existingManifest?.resources.find(
      (candidate) => candidate.path === originalPath && candidate.kind === resource.kind,
    )
    let targetPath = originalPath
    let shouldWrite = true

    if (existingFile && !existingManifest) {
      targetPath = createUniqueResourcePath(originalPath)
    } else if (existingFile && previousResource) {
      if (await fileMatchesBytes(existingFile, bytes)) shouldWrite = false
      else targetPath = createUniqueResourcePath(originalPath)
    }

    if (targetPath !== originalPath && await findDirectoryFile(directory, targetPath)) {
      throw new Error(`项目资源路径冲突：${targetPath}`)
    }
    replacements.set(originalPath, targetPath)
    if (shouldWrite) writes.push({ path: targetPath, bytes })
  }

  return { replacements, writes }
}

function remapProjectResourceReferences(
  manifest: A2DProjectManifest,
  replacements: Map<string, string>,
): void {
  const remap = (path: string | null): string | null => {
    if (path === null) return null
    const replacement = replacements.get(path)
    if (!replacement) throw new Error(`项目清单引用了未打包的资源：${path}`)
    return replacement
  }

  for (const resource of manifest.resources) resource.path = remap(resource.path)!
  for (const role of manifest.roles) {
    role.reference_audio_path = remap(role.reference_audio_path)
    for (const emotion of Object.keys(role.avatar_assets)) {
      role.avatar_assets[emotion] = remap(role.avatar_assets[emotion]!)!
    }
  }
  for (const line of manifest.script.lines) {
    line.audio_path = remap(line.audio_path)
    if (!line.overlay) continue
    line.overlay.ref_audio_path = remap(line.overlay.ref_audio_path ?? null)
    line.overlay.background = remap(line.overlay.background)
    line.overlay.bgm = remap(line.overlay.bgm)
    for (const image of line.overlay.image_overlays) image.path = remap(image.path)!
  }
  for (const stage of manifest.script.stages) {
    stage.default_background = remap(stage.default_background)
  }
}

/** Remove the empty manifest created by a failed first save so the user can retry. */
async function removeNewProjectManifest(directory: FileSystemDirectoryHandle): Promise<void> {
  try {
    await directory.removeEntry('project.json')
  } catch (error) {
    if (!isNotFoundError(error)) throw error
  }
}

/** Save the current project as the same readable v2 directory used by ZIP export. */
export async function saveA2DProjectToDirectory(directory: FileSystemDirectoryHandle): Promise<void> {
  const script = useScriptStore()
  const archive = await packA2DProject(buildExportEnvelope(), script.projectName)
  const archiveFile = new File([copyBytesToArrayBuffer(archive)], 'project.a2d.zip', { type: 'application/zip' })
  const files = await readProjectArchive(archiveFile)
  const sourceManifestBytes = files.get('project.json')
  if (!sourceManifestBytes) throw new Error('项目包缺少 project.json')
  const parsedManifest = parseManifest(sourceManifestBytes)
  if ('error' in parsedManifest) throw new Error(parsedManifest.error)
  const manifest = parsedManifest.manifest
  const existingManifest = await hasExistingProjectManifest(directory)
  const resourcePlan = await planDirectoryResourceWrites(directory, manifest, files, existingManifest)
  remapProjectResourceReferences(manifest, resourcePlan.replacements)

  const validation = validateProjectManifest(manifest)
  if (!validation.ok) throw new Error(`导出项目清单无效：${validation.error}`)
  const manifestBytes = new TextEncoder().encode(JSON.stringify(manifest, null, 2))
  if (manifestBytes.byteLength > A2D_PROJECT_MAX_MANIFEST_BYTES) throw new Error('project.json 超过 10 MiB 限制')
  let expandedBytes = manifestBytes.byteLength
  for (const resource of manifest.resources) {
    expandedBytes = nextProjectByteCount(expandedBytes, resource.byte_length, A2D_PROJECT_MAX_EXPANDED_BYTES, 'directory expanded bytes')
  }

  for (const resource of resourcePlan.writes) await writeDirectoryFile(directory, resource.path, resource.bytes)
  try {
    await writeDirectoryFile(directory, 'project.json', manifestBytes)
  } catch (error) {
    if (!existingManifest) await removeNewProjectManifest(directory)
    throw error
  }
}

/** Open a readable v2 project directory, rebuilding a ZIP for the shared importer validation. */
export async function openA2DProjectFromDirectory(directory: FileSystemDirectoryHandle): Promise<ImportResult> {
  try {
    const manifestFile = await readDirectoryFile(directory, 'project.json')
    if (manifestFile.size > A2D_PROJECT_MAX_MANIFEST_BYTES) throw new Error('project.json 超过 10 MiB 限制')
    const manifestBytes = new Uint8Array(await manifestFile.arrayBuffer())
    let rawManifest: unknown
    try {
      rawManifest = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(manifestBytes))
    } catch {
      throw new Error('project.json 不是有效的 UTF-8 JSON')
    }
    const validation = validateProjectManifest(rawManifest)
    if (!validation.ok) throw new Error(validation.error || '项目清单无效')

    const manifest = rawManifest as A2DProjectManifest
    const files: Record<string, Uint8Array> = { 'project.json': manifestBytes }
    let expandedBytes = manifestBytes.byteLength
    for (const resource of manifest.resources) {
      if (resource.byte_length > A2D_PROJECT_MAX_ENTRY_BYTES) throw new Error(`项目资源超过 128 MiB 限制：${resource.path}`)
      const file = await readDirectoryFile(directory, resource.path)
      if (file.size !== resource.byte_length) throw new Error(`项目资源大小与清单不一致：${resource.path}`)
      expandedBytes = nextProjectByteCount(expandedBytes, file.size, A2D_PROJECT_MAX_EXPANDED_BYTES, 'directory expanded bytes')
      files[resource.path] = new Uint8Array(await file.arrayBuffer())
    }

    const archive = await writeProjectArchive(files)
    if (archive.byteLength > A2D_PROJECT_MAX_ARCHIVE_BYTES) throw new Error('项目压缩包超过 512 MiB 限制')
    return importA2DProject(new File([copyBytesToArrayBuffer(archive)], 'project.a2d.zip', { type: 'application/zip' }))
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : '项目文件夹读取失败' }
  }
}

export async function pickA2DProjectDirectory(mode: 'read' | 'readwrite'): Promise<FileSystemDirectoryHandle> {
  const pickerWindow = window as A2DDirectoryPickerWindow
  if (!pickerWindow.showDirectoryPicker) {
    throw new Error('当前浏览器不支持项目文件夹读写，请使用 ZIP 项目包导入或导出')
  }
  return pickerWindow.showDirectoryPicker({ mode })
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
  window.setTimeout(() => URL.revokeObjectURL(url), DOWNLOAD_URL_REVOKE_DELAY_MS)
}

function parseManifest(bytes: Uint8Array): { manifest: A2DProjectManifest } | { error: string } {
  if (bytes.byteLength > A2D_PROJECT_MAX_MANIFEST_BYTES) return { error: 'project.json 超过 10 MiB 限制' }
  let raw: unknown
  try {
    raw = JSON.parse(new TextDecoder('utf-8', { fatal: true }).decode(bytes))
  } catch {
    return { error: 'project.json 不是有效的 UTF-8 JSON' }
  }
  if (typeof raw === 'object' && raw !== null && !Array.isArray(raw)
    && 'version' in raw && !('schema_version' in raw)) {
    return { error: '只支持 A2D 项目 v2；旧版项目包不兼容' }
  }
  const validation = validateProjectManifest(raw)
  if (!validation.ok) return { error: validation.error || '项目清单无效' }
  return { manifest: raw as A2DProjectManifest }
}

function validateArchiveContents(
  manifest: A2DProjectManifest,
  archive: Map<string, Uint8Array>,
): string | null {
  const expectedPaths = new Set(['project.json', ...manifest.resources.map((resource) => resource.path)])
  if (archive.size !== expectedPaths.size) return '项目压缩包包含清单之外的文件'
  for (const resource of manifest.resources) {
    const bytes = archive.get(resource.path)
    if (!bytes) return `项目包缺少资源：${resource.path}`
    if (bytes.byteLength !== resource.byte_length) return `项目资源大小与清单不一致：${resource.path}`
  }
  return null
}

function createObjectUrl(bytes: Uint8Array, mediaType: string, urls: string[]): string {
  const copy = new Uint8Array(bytes.byteLength)
  copy.set(bytes)
  const url = URL.createObjectURL(new Blob([copy], { type: mediaType }))
  urls.push(url)
  return url
}

function mapResourceUrls(manifest: A2DProjectManifest, archive: Map<string, Uint8Array>, urls: string[]): Map<string, string> {
  const resourceUrls = new Map<string, string>()
  for (const resource of manifest.resources) {
    const bytes = archive.get(resource.path)
    if (!bytes) throw new Error(`项目包缺少资源：${resource.path}`)
    resourceUrls.set(resource.path, createObjectUrl(bytes, resource.media_type, urls))
  }
  return resourceUrls
}

function resolveResourceUrl(path: string | null | undefined, urls: Map<string, string>): string | null {
  if (path == null || path === '') return null
  const url = urls.get(path)
  if (!url) throw new Error(`项目资源未验证：${path}`)
  return url
}

function createRuntimeRoles(roles: A2DProjectRole[], urls: Map<string, string>): {
  gameRoles: ExportEnvelope['game']['gameRoles']
  presentRoleIds: number[]
  roleIdsByKey: Map<string, number>
  avatarUrls: Map<string, string>
} {
  const gameRoles: ExportEnvelope['game']['gameRoles'] = {}
  const presentRoleIds: number[] = []
  const roleIdsByKey = new Map<string, number>()
  const avatarUrls = new Map<string, string>()
  roles.forEach((projectRole, index) => {
    const roleId = PROJECT_RUNTIME_ROLE_ID_START - index
    roleIdsByKey.set(projectRole.script_role_key, roleId)
    presentRoleIds.push(roleId)
    gameRoles[roleId] = {
      roleId,
      scriptRoleKey: projectRole.script_role_key,
      roleName: projectRole.display_name,
      roleSubTitle: projectRole.subtitle || '',
      thinkMessage: '',
      emotion: projectRole.emotion || '正常',
      originalEmotion: projectRole.original_emotion || projectRole.emotion || '正常',
      scale: projectRole.scale ?? 1,
      offsetX: projectRole.offset_x ?? 0,
      offsetY: projectRole.offset_y ?? 0,
      bubbleTop: projectRole.bubble_top ?? 5,
      bubbleLeft: projectRole.bubble_left ?? 20,
      show: projectRole.show ?? true,
      clothes: {},
      clothesName: projectRole.clothes_name || 'default',
      bodyPart: {},
      character_folder: '',
    }
    for (const [emotion, path] of Object.entries(projectRole.avatar_assets)) {
      const avatarUrl = resolveResourceUrl(path, urls)
      if (avatarUrl) {
        avatarUrls.set(
          getProjectAvatarRegistryKey(projectRole.script_role_key, gameRoles[roleId].clothesName, emotion),
          avatarUrl,
        )
      }
    }
  })
  return { gameRoles, presentRoleIds, roleIdsByKey, avatarUrls }
}

function restoreOverlay(
  line: A2DProjectLine,
  roleIdsByKey: Map<string, number>,
  urls: Map<string, string>,
): LineOverlay | null {
  const overlay = line.overlay
  if (!overlay) return null
  const characterId = overlay.character_role_key ? roleIdsByKey.get(overlay.character_role_key) : undefined
  if (overlay.character_role_key && characterId === undefined) throw new Error(`未知角色键：${overlay.character_role_key}`)
  return {
    line_id: line.id,
    character_id: characterId ?? -1,
    ref_audio_path: resolveResourceUrl(overlay.ref_audio_path, urls),
    gsv_params: overlay.gsv_params ? { ...overlay.gsv_params } : null,
    sprite_positions: overlay.sprite_positions ? { ...overlay.sprite_positions } : null,
    background: resolveResourceUrl(overlay.background, urls),
    text_overlays: overlay.text_overlays.map((item) => ({ ...item })) as TextOverlay[],
    image_overlays: overlay.image_overlays.map((item) => ({
      ...item,
      path: resolveResourceUrl(item.path, urls) || '',
    })) as ImageOverlay[],
    bgm: resolveResourceUrl(overlay.bgm, urls) || '',
    bgm_volume: overlay.bgm_volume,
    bgm_loop: overlay.bgm_loop,
  }
}

function restoreLine(
  line: A2DProjectLine,
  roleIdsByKey: Map<string, number>,
  urls: Map<string, string>,
): ScriptLine {
  if (line.speaker !== 'narrator' && !roleIdsByKey.has(line.speaker)) throw new Error(`未知角色键：${line.speaker}`)
  return {
    id: line.id,
    speaker: line.speaker,
    ...(line.emotion !== undefined ? { emotion: line.emotion } : {}),
    display_text: line.display_text,
    tts_text: line.tts_text,
    ...(line.action !== undefined ? { action: line.action } : {}),
    index: line.index,
    ...(line.batch_index !== undefined ? { batch_index: line.batch_index } : {}),
    ...(line.batch_total !== undefined ? { batch_total: line.batch_total } : {}),
    audio_path: resolveResourceUrl(line.audio_path, urls),
    overlay: restoreOverlay(line, roleIdsByKey, urls),
    stage_id: line.stage_id,
  }
}

function createRuntimeEnvelope(
  manifest: A2DProjectManifest,
  roleIdsByKey: Map<string, number>,
  urls: Map<string, string>,
  gameRoles: ExportEnvelope['game']['gameRoles'],
  presentRoleIds: number[],
): ExportEnvelope {
  return {
    version: 2,
    exportedAt: manifest.exported_at,
    script: {
      version: 2,
      exportedAt: manifest.exported_at,
      projectName: manifest.script.project_name,
      lines: manifest.script.lines.map((line) => restoreLine(line, roleIdsByKey, urls)),
      phase: 'idle',
      selectedLineId: null,
      playingLineId: null,
      editedText: {},
      activeTab: 'script',
    },
    game: { gameRoles, presentRoleIds },
    stages: manifest.script.stages.map((stage) => ({
      id: stage.id,
      default_background: resolveResourceUrl(stage.default_background, urls) || '',
    })),
  }
}

function revokeUrls(urls: string[]): void {
  urls.forEach((url) => URL.revokeObjectURL(url))
}

export async function unpackA2DProject(file: File): Promise<ImportResult> {
  if (file.size > A2D_PROJECT_MAX_ARCHIVE_BYTES) return { ok: false, error: '项目压缩包超过 512 MiB 限制' }
  let archive: Map<string, Uint8Array>
  try {
    archive = await readProjectArchive(file)
  } catch (error) {
    return { ok: false, error: error instanceof Error ? error.message : '项目压缩包损坏或无法读取' }
  }
  const manifestBytes = archive.get('project.json')
  if (!manifestBytes) return { ok: false, error: '项目包缺少 project.json' }
  const parsed = parseManifest(manifestBytes)
  if ('error' in parsed) return { ok: false, error: parsed.error }
  const manifest = parsed.manifest
  if (manifest.format !== A2D_PROJECT_FORMAT || manifest.schema_version !== A2D_PROJECT_SCHEMA_VERSION) {
    return { ok: false, error: '只支持 A2D 项目 v2；旧版项目包不兼容' }
  }
  const archiveError = validateArchiveContents(manifest, archive)
  if (archiveError) return { ok: false, error: archiveError }

  const objectUrls: string[] = []
  try {
    const resourceUrls = mapResourceUrls(manifest, archive, objectUrls)
    const runtimeRoles = createRuntimeRoles(manifest.roles, resourceUrls)
    const envelope = createRuntimeEnvelope(
      manifest,
      runtimeRoles.roleIdsByKey,
      resourceUrls,
      runtimeRoles.gameRoles,
      runtimeRoles.presentRoleIds,
    )
    const importFile = new File([strToU8(JSON.stringify(envelope))], 'project.a2d.json', { type: 'application/json' })
    const result = await importSession(importFile)
    if (!result.ok) {
      revokeUrls(objectUrls)
      return result
    }
    registerImportedProjectAssets(runtimeRoles.avatarUrls, objectUrls)
    return result
  } catch (error) {
    revokeUrls(objectUrls)
    return { ok: false, error: error instanceof Error ? error.message : '项目资源还原失败' }
  }
}

export async function importA2DProject(file: File): Promise<ImportResult> {
  const result = await unpackA2DProject(file)
  if (result.ok) useScriptStore().setActiveTab('script')
  return result
}
