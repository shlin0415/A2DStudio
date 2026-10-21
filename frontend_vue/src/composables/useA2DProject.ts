import { strToU8 } from 'fflate'
import { useGameStore } from '@/stores/modules/game'
import { useScriptStore, type ImageOverlay, type LineOverlay, type ScriptLine, type TextOverlay } from '@/stores/modules/script'
import {
  A2D_PROJECT_FORMAT,
  A2D_PROJECT_MAX_ARCHIVE_BYTES,
  A2D_PROJECT_MAX_MANIFEST_BYTES,
  A2D_PROJECT_SCHEMA_VERSION,
  validateProjectManifest,
  type A2DProjectLine,
  type A2DProjectManifest,
  type A2DProjectRole,
} from './a2d-project-format'
import { readProjectArchive } from './a2d-project-archive'
import { packA2DProject } from './a2d-project-export'
import { registerImportedProjectAssets, getProjectAvatarRegistryKey } from './a2d-project-runtime-assets'
import { buildExportEnvelope, importSession, type ExportEnvelope, type ImportResult } from './useA2DSaveLoad'

const DOWNLOAD_URL_REVOKE_DELAY_MS = 1000
const PROJECT_RUNTIME_ROLE_ID_START = -1_000_000

function safeTitle(title: string): string {
  return title.replace(/[<>:"/\\|?*\u0000-\u001f]/g, '_').trim() || 'a2d-project'
}

export { packA2DProject }

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
