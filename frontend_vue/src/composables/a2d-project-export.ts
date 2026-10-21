import type { ExportEnvelope } from './useA2DSaveLoad'
import {
  A2D_PROJECT_FORMAT,
  A2D_PROJECT_MAX_ARCHIVE_BYTES,
  A2D_PROJECT_MAX_ENTRY_BYTES,
  A2D_PROJECT_MAX_EXPANDED_BYTES,
  A2D_PROJECT_MAX_ENTRIES,
  A2D_PROJECT_MAX_MANIFEST_BYTES,
  A2D_PROJECT_SCHEMA_VERSION,
  type A2DProjectAssetKind,
  type A2DProjectLine,
  type A2DProjectManifest,
  type A2DProjectResource,
  type A2DProjectRole,
  validateProjectManifest,
} from './a2d-project-format'
import { writeProjectArchive } from './a2d-project-archive'
import { EMOTION_CONFIG_EMO } from '@/controllers/emotion/config'
import { getImportedProjectAvatar, isImportedProjectAssetUrl } from './a2d-project-runtime-assets'

const MAX_MEDIA_BYTES = A2D_PROJECT_MAX_ENTRY_BYTES
const MAX_EXPANDED_BYTES = A2D_PROJECT_MAX_EXPANDED_BYTES
const ALLOWED_GSV_PARAMETER_KEYS = ['speed_factor', 'top_k', 'top_p', 'temperature'] as const

interface DownloadedAsset {
  bytes: Uint8Array
  mediaType: string
  extension: string
}

interface ExportContext {
  envelope: ExportEnvelope
  archiveEntries: Record<string, Uint8Array>
  resources: A2DProjectResource[]
  assetPaths: Map<string, string>
  roleKeysById: Map<number, string>
  rolesByKey: Map<string, A2DProjectRole>
  assetCountByKind: Map<A2DProjectAssetKind, number>
  totalBytes: number
}

function validateKnownRoute(source: string, kind: A2DProjectAssetKind): string {
  const fieldLabel = `${kind} 素材`
  if (source.startsWith('blob:')) {
    if (kind !== 'line_audio' && !isImportedProjectAssetUrl(source)) {
      throw new Error(`${fieldLabel}: 只允许使用已导入项目中的临时资源`)
    }
    return source
  }
  if (source.startsWith('data:')) {
    if (kind !== 'line_audio') throw new Error(`${fieldLabel}: 只允许语音使用临时 URL`)
    return source
  }

  let url: URL
  try {
    url = new URL(source, window.location.origin)
    if (source.startsWith('/audio/')) {
      url = new URL(`http://${window.location.hostname}:8765${source}`)
    }
  } catch {
    throw new Error(`${fieldLabel}: 素材 URL 无效`)
  }
  const current = new URL(window.location.origin)
  const isSameOrigin = url.origin === current.origin
  const isLocalAudio = url.protocol === 'http:' && url.hostname === current.hostname && url.port === '8765'
    && /^\/audio\/[A-Za-z0-9._-]+\.wav$/i.test(url.pathname)
  if (!isSameOrigin && !isLocalAudio) throw new Error(`${fieldLabel}: 只支持本机 A2D 素材`)
  if (url.username || url.password || url.hash) throw new Error(`${fieldLabel}: 素材 URL 不规范`)
  if (kind === 'line_audio') {
    const validApiAudio = isSameOrigin && /^\/api\/a2d\/save\/audio\/[A-Za-z0-9_-]+\/[A-Za-z0-9_-]+\.wav$/i.test(url.pathname)
    if (!isLocalAudio && !validApiAudio) throw new Error('line_audio 素材: 只支持本机生成的 WAV 文件')
    if (url.search) throw new Error('line_audio 素材: WAV 路径不能包含查询参数')
    return url.href
  }
  if (!isSameOrigin || url.search) throw new Error(`${fieldLabel}: 不支持未知的素材地址`)
  if (kind === 'background' && !isSingleFileRoute(url.pathname, [
    '/api/v1/chat/script/background_file/', '/api/v1/chat/background/background_file/',
  ])) throw new Error('background 素材: 不支持该资源路径')
  if (kind === 'image' && !isSingleFileRoute(url.pathname, ['/api/v1/chat/script/pic_file/'])) {
    throw new Error('image 素材: 不支持该资源路径')
  }
  if (kind === 'music' && !isSingleFileRoute(url.pathname, [
    '/api/v1/chat/script/music_file/', '/api/v1/chat/back-music/music_file/',
  ])) throw new Error('music 素材: 不支持该资源路径')
  if (kind === 'avatar' && !isAvatarRoute(url.pathname)) {
    throw new Error('avatar 素材: 不支持该资源路径')
  }
  if (kind === 'reference_audio' && !/^\/api\/a2d\/project-assets\/reference-audio\/[A-Za-z0-9_-]{1,64}$/.test(url.pathname)) {
    throw new Error('reference_audio 素材: 不支持该资源路径')
  }
  return url.href
}

function isSingleFileRoute(pathname: string, prefixes: string[]): boolean {
  return prefixes.some((prefix) => {
    if (!pathname.startsWith(prefix)) return false
    return isSafeUrlSegment(pathname.slice(prefix.length))
  })
}

function isSafeUrlSegment(encodedSegment: string): boolean {
  let segment: string
  try {
    segment = decodeURIComponent(encodedSegment)
  } catch {
    return false
  }
  return segment.length > 0 && segment !== '.' && segment !== '..'
    && !/[\\/:\u0000-\u001f]/.test(segment)
}

function isAvatarRoute(pathname: string): boolean {
  const prefix = '/api/v1/chat/character/get_avatar/'
  if (!pathname.startsWith(prefix)) return false
  const parts = pathname.slice(prefix.length).split('/')
  const [roleId, encodedEmotion, encodedClothes] = parts
  if (parts.length !== 3 || !roleId || !/^[0-9]+$/.test(roleId)) return false
  if (!encodedEmotion || !encodedClothes || !isSafeUrlSegment(encodedEmotion) || !isSafeUrlSegment(encodedClothes)) return false
  let emotion: string
  let clothes: string
  try {
    emotion = decodeURIComponent(encodedEmotion)
    clothes = decodeURIComponent(encodedClothes)
  } catch {
    return false
  }
  return /^[\p{L}\p{N}_-]+$/u.test(emotion) && /^[\p{L}\p{N}_. -]+$/u.test(clothes)
}

async function readResponseBytes(response: Response, field: string): Promise<Uint8Array> {
  const declaredLength = Number(response.headers.get('content-length'))
  if (Number.isFinite(declaredLength) && declaredLength > MAX_MEDIA_BYTES) throw new Error(`${field}: 单个素材超过 128 MiB 限制`)
  if (!response.body) throw new Error(`${field}: 响应没有素材内容`)
  const reader = response.body.getReader()
  const chunks: Uint8Array[] = []
  let size = 0
  try {
    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      size += value.byteLength
      if (size > MAX_MEDIA_BYTES) throw new Error(`${field}: 单个素材超过 128 MiB 限制`)
      chunks.push(value.slice())
    }
  } catch (error) {
    await reader.cancel().catch(() => undefined)
    throw error
  } finally {
    reader.releaseLock()
  }
  const bytes = new Uint8Array(size)
  let offset = 0
  for (const chunk of chunks) {
    bytes.set(chunk, offset)
    offset += chunk.byteLength
  }
  return bytes
}

function extensionFromUrl(url: string): string | null {
  try {
    const pathname = new URL(url).pathname
    const match = pathname.match(/\.([A-Za-z0-9]{1,8})$/)
    return match?.[1] ? `.${match[1].toLowerCase()}` : null
  } catch {
    return null
  }
}

function extensionFromMediaType(mediaType: string): string {
  const extensions: Record<string, string> = {
    'audio/wav': '.wav', 'audio/mpeg': '.mp3', 'audio/ogg': '.ogg', 'audio/flac': '.flac',
    'audio/mp4': '.m4a', 'audio/webm': '.webm', 'image/png': '.png', 'image/jpeg': '.jpg',
    'image/gif': '.gif', 'image/webp': '.webp', 'image/bmp': '.bmp', 'image/avif': '.avif',
  }
  return extensions[mediaType] || ''
}

function validateMediaType(kind: A2DProjectAssetKind, mediaType: string, field: string): void {
  if ((kind === 'line_audio' || kind === 'reference_audio') && mediaType !== 'audio/wav') {
    throw new Error(`${field}: 参考语音必须是 WAV 格式`)
  }
  if ((kind === 'background' || kind === 'image' || kind === 'avatar') && !mediaType.startsWith('image/')) {
    throw new Error(`${field}: 服务器返回的不是图片`)
  }
  if (kind === 'music' && !mediaType.startsWith('audio/')) throw new Error(`${field}: 服务器返回的不是音频`)
}

async function downloadAsset(kind: A2DProjectAssetKind, source: string, field: string): Promise<DownloadedAsset> {
  const url = validateKnownRoute(source, kind)
  let response: Response
  try {
    response = await fetch(url)
  } catch {
    throw new Error(`${field}: 读取素材失败`)
  }
  if (!response.ok) throw new Error(`${field}: 读取素材失败（HTTP ${response.status}）`)
  const mediaType = (response.headers.get('content-type') || '').split(';', 1)[0]?.trim().toLowerCase() || ''
  validateMediaType(kind, mediaType, field)
  const bytes = await readResponseBytes(response, field)
  if (bytes.byteLength === 0) throw new Error(`${field}: 素材内容为空`)
  const extension = kind === 'line_audio' || kind === 'reference_audio'
    ? '.wav'
    : extensionFromUrl(url) || extensionFromMediaType(mediaType)
  if (!extension) throw new Error(`${field}: 無法判斷素材格式`)
  return { bytes, mediaType, extension }
}

function assetKey(kind: A2DProjectAssetKind, source: string): string {
  return `${kind}\u0000${source}`
}

async function addAsset(context: ExportContext, kind: A2DProjectAssetKind, source: string, field: string): Promise<string> {
  const normalizedSource = validateKnownRoute(source, kind)
  const key = assetKey(kind, normalizedSource)
  const existingPath = context.assetPaths.get(key)
  if (existingPath) return existingPath
  if (context.resources.length + 1 >= A2D_PROJECT_MAX_ENTRIES) throw new Error('项目资源条目超过 1,024 项限制')
  const asset = await downloadAsset(kind, normalizedSource, field)
  context.totalBytes += asset.bytes.byteLength
  if (context.totalBytes > MAX_EXPANDED_BYTES) throw new Error('项目资源解压总量超过 512 MiB 限制')
  const sequence = (context.assetCountByKind.get(kind) || 0) + 1
  context.assetCountByKind.set(kind, sequence)
  const directory = getAssetDirectory(kind)
  const filePrefix = kind === 'line_audio' ? 'line' : 'asset'
  const archivePath = `assets/${directory}/${filePrefix}-${String(sequence).padStart(4, '0')}${asset.extension}`
  context.archiveEntries[archivePath] = asset.bytes
  context.resources.push({ path: archivePath, kind, media_type: asset.mediaType, byte_length: asset.bytes.byteLength })
  context.assetPaths.set(key, archivePath)
  return archivePath
}

function getAssetDirectory(kind: A2DProjectAssetKind): string {
  const directories: Record<A2DProjectAssetKind, string> = {
    line_audio: 'audio', background: 'backgrounds', image: 'images', music: 'music',
    reference_audio: 'references', avatar: 'avatars',
  }
  return directories[kind]
}

function mappedEmotion(emotion: string): string | null {
  const mapped = EMOTION_CONFIG_EMO[emotion]
  if (mapped === 'none') return null
  return mapped || '正常'
}

function roleFromRuntime(role: ExportEnvelope['game']['gameRoles'][number], roleKey: string): A2DProjectRole {
  return {
    script_role_key: roleKey,
    display_name: role.roleName,
    subtitle: role.roleSubTitle,
    emotion: role.emotion,
    original_emotion: role.originalEmotion,
    scale: role.scale,
    offset_x: role.offsetX,
    offset_y: role.offsetY,
    bubble_top: role.bubbleTop,
    bubble_left: role.bubbleLeft,
    show: role.show,
    clothes_name: role.clothesName === '默认' || !role.clothesName ? 'default' : role.clothesName,
    avatar_assets: {},
    reference_audio_path: null,
  }
}

function createExportContext(envelope: ExportEnvelope): ExportContext {
  const roleKeysById = new Map<number, string>()
  const rolesByKey = new Map<string, A2DProjectRole>()
  for (const roleId of envelope.game.presentRoleIds) {
    const runtimeRole = envelope.game.gameRoles[roleId]
    const roleKey = runtimeRole?.scriptRoleKey
    if (!runtimeRole || !roleKey) throw new Error(`角色 ${roleId}: 缺少稳定的 script_role_key，无法导出项目`)
    if (!/^[A-Za-z0-9_-]{1,64}$/.test(roleKey)) throw new Error('角色 script_role_key 格式无效')
    if (rolesByKey.has(roleKey)) throw new Error(`角色 ${roleKey}: script_role_key 重复`)
    roleKeysById.set(roleId, roleKey)
    rolesByKey.set(roleKey, roleFromRuntime(runtimeRole, roleKey))
  }
  return {
    envelope,
    archiveEntries: {},
    resources: [],
    assetPaths: new Map(),
    roleKeysById,
    rolesByKey,
    assetCountByKind: new Map(),
    totalBytes: 0,
  }
}

function portableOverlay(context: ExportContext, line: ExportEnvelope['script']['lines'][number]): A2DProjectLine['overlay'] {
  const overlay = line.overlay
  if (!overlay) return null
  const speakerRoleKey = line.speaker === 'narrator' ? undefined : line.speaker
  const characterRoleKey = context.roleKeysById.get(overlay.character_id)
  const roleKey = characterRoleKey || speakerRoleKey
  const refPath = overlay.ref_audio_path
  const gsvParams: Record<string, number> = {}
  for (const key of ALLOWED_GSV_PARAMETER_KEYS) {
    const value = overlay.gsv_params?.[key]
    if (typeof value === 'number' && Number.isFinite(value)) gsvParams[key] = value
  }
  const spritePositions: Record<string, { x: number; y: number; scale: number }> = {}
  for (const [key, position] of Object.entries(overlay.sprite_positions || {})) {
    const mappedRoleKey = context.roleKeysById.has(Number(key)) ? context.roleKeysById.get(Number(key))! : key
    spritePositions[mappedRoleKey] = { x: position.x, y: position.y, scale: position.scale }
  }
  return {
    character_role_key: characterRoleKey || null,
    ref_audio_path: refPath ? `pending:${roleKey || ''}` : null,
    gsv_params: Object.keys(gsvParams).length ? gsvParams : null,
    sprite_positions: Object.keys(spritePositions).length ? spritePositions : null,
    background: overlay.background,
    text_overlays: overlay.text_overlays.map((item) => ({
      id: item.id,
      text: item.text,
      x: item.x,
      y: item.y,
      width: item.width,
      font_size: item.font_size,
      color: item.color,
      opacity: item.opacity,
      z: item.z,
    })),
    image_overlays: overlay.image_overlays.map((item) => ({
      id: item.id,
      path: item.path,
      x: item.x,
      y: item.y,
      w: item.w,
      h: item.h,
      opacity: item.opacity,
      z: item.z,
    })),
    bgm: overlay.bgm || null,
    bgm_volume: overlay.bgm_volume,
    bgm_loop: overlay.bgm_loop,
  }
}

function portableLine(context: ExportContext, line: ExportEnvelope['script']['lines'][number]): A2DProjectLine {
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
    audio_path: line.audio_path,
    overlay: portableOverlay(context, line),
    stage_id: line.stage_id,
  }
}

async function collectRoleAssets(context: ExportContext): Promise<void> {
  for (const [roleKey, role] of context.rolesByKey) {
    const runtimeRoleId = [...context.roleKeysById.entries()].find(([, key]) => key === roleKey)?.[0]
    if (runtimeRoleId === undefined) continue
    const referenceLine = context.envelope.script.lines.find((line) => {
      const overlayRoleKey = line.overlay
        ? context.roleKeysById.get(line.overlay.character_id) || line.speaker
        : line.speaker
      return overlayRoleKey === roleKey && Boolean(line.overlay?.ref_audio_path)
    })
    if (referenceLine) {
      const importedReferenceAudio = referenceLine.overlay?.ref_audio_path
      const url = importedReferenceAudio?.startsWith('blob:')
        ? importedReferenceAudio
        : `/api/a2d/project-assets/reference-audio/${encodeURIComponent(roleKey)}`
      role.reference_audio_path = await addAsset(context, 'reference_audio', url, `roles.${roleKey}.reference_audio_path`)
    }
    const emotions = new Set<string>()
    const currentEmotion = mappedEmotion(role.emotion || '正常')
    if (currentEmotion) emotions.add(currentEmotion)
    for (const line of context.envelope.script.lines) {
      if (line.speaker === roleKey && line.emotion) {
        const emotion = mappedEmotion(line.emotion)
        if (emotion) emotions.add(emotion)
      }
    }
    const clothesName = role.clothes_name || 'default'
    for (const emotion of emotions) {
      const importedAvatar = getImportedProjectAvatar(roleKey, clothesName, emotion)
      const url =
        importedAvatar ||
        `/api/v1/chat/character/get_avatar/${runtimeRoleId}/${encodeURIComponent(emotion)}/${encodeURIComponent(clothesName)}`
      role.avatar_assets[emotion] = await addAsset(context, 'avatar', url, `roles.${roleKey}.avatar_assets.${emotion}`)
    }
  }
}

async function collectLineAssets(context: ExportContext, lines: A2DProjectLine[]): Promise<void> {
  for (let index = 0; index < lines.length; index += 1) {
    const portable = lines[index]!
    const source = context.envelope.script.lines[index]!
    if (source.audio_path) portable.audio_path = await addAsset(context, 'line_audio', source.audio_path, `script.lines[${index}].audio_path`)
    const overlay = portable.overlay
    if (!overlay) continue
    if (source.overlay?.ref_audio_path) {
      const roleKey = context.roleKeysById.get(source.overlay.character_id) || source.speaker
      const role = context.rolesByKey.get(roleKey)
      if (!role?.reference_audio_path) throw new Error(`roles.${roleKey}.reference_audio_path: 引用语音未能打包`)
      overlay.ref_audio_path = role.reference_audio_path
    } else {
      overlay.ref_audio_path = null
    }
    if (overlay.background) overlay.background = await addAsset(context, 'background', overlay.background, `script.lines[${index}].overlay.background`)
    if (overlay.bgm) overlay.bgm = await addAsset(context, 'music', overlay.bgm, `script.lines[${index}].overlay.bgm`)
    for (let imageIndex = 0; imageIndex < overlay.image_overlays.length; imageIndex += 1) {
      const image = overlay.image_overlays[imageIndex]!
      image.path = await addAsset(context, 'image', source.overlay!.image_overlays[imageIndex]!.path, `script.lines[${index}].overlay.image_overlays[${imageIndex}].path`)
    }
  }
}

async function collectStageAssets(context: ExportContext, manifest: A2DProjectManifest): Promise<void> {
  for (let index = 0; index < manifest.script.stages.length; index += 1) {
    const source = context.envelope.stages?.[index]?.default_background
    if (source) manifest.script.stages[index]!.default_background = await addAsset(
      context, 'background', source, `script.stages[${index}].default_background`,
    )
  }
}

/** Create a portable A2D v2 archive from the current runtime envelope. */
export async function packA2DProject(sourceEnvelope: ExportEnvelope, title: string): Promise<Uint8Array> {
  const envelope = JSON.parse(JSON.stringify(sourceEnvelope)) as ExportEnvelope
  const context = createExportContext(envelope)
  const projectTitle = title.trim() || '未命名剧本'
  const lines = envelope.script.lines.map((line) => portableLine(context, line))
  const manifest: A2DProjectManifest = {
    format: A2D_PROJECT_FORMAT,
    schema_version: A2D_PROJECT_SCHEMA_VERSION,
    title: projectTitle,
    exported_at: new Date().toISOString(),
    roles: [...context.rolesByKey.values()],
    script: {
      project_name: projectTitle,
      lines,
      stages: (envelope.stages || []).map((stage) => ({ id: stage.id, default_background: stage.default_background || null })),
    },
    resources: context.resources,
  }
  await collectRoleAssets(context)
  await collectLineAssets(context, lines)
  await collectStageAssets(context, manifest)
  const validation = validateProjectManifest(manifest)
  if (!validation.ok) throw new Error(`导出项目清单无效：${validation.error}`)
  context.archiveEntries['project.json'] = new TextEncoder().encode(JSON.stringify(manifest, null, 2))
  if (context.archiveEntries['project.json'].byteLength > A2D_PROJECT_MAX_MANIFEST_BYTES) {
    throw new Error('project.json 超过 10 MiB 限制')
  }
  if (context.totalBytes + context.archiveEntries['project.json'].byteLength > MAX_EXPANDED_BYTES) {
    throw new Error('项目解压总量超过 512 MiB 限制')
  }
  const archive = await writeProjectArchive(context.archiveEntries)
  if (archive.byteLength > A2D_PROJECT_MAX_ARCHIVE_BYTES) throw new Error('项目压缩包超过 512 MiB 限制')
  return archive
}
