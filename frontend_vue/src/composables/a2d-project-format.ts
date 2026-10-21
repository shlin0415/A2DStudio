export const A2D_PROJECT_FORMAT = 'a2d-studio-project'
export const A2D_PROJECT_SCHEMA_VERSION = 2
export const A2D_PROJECT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
export const A2D_PROJECT_MAX_ENTRY_BYTES = 128 * 1024 * 1024
export const A2D_PROJECT_MAX_EXPANDED_BYTES = 512 * 1024 * 1024
export const A2D_PROJECT_MAX_ENTRIES = 1024
export const A2D_PROJECT_MAX_MANIFEST_BYTES = 10 * 1024 * 1024

export type A2DProjectAssetKind =
  | 'line_audio'
  | 'background'
  | 'image'
  | 'music'
  | 'reference_audio'
  | 'avatar'

export interface A2DProjectResource {
  path: string
  kind: A2DProjectAssetKind
  media_type: string
  byte_length: number
}

export interface A2DProjectRole {
  script_role_key: string
  display_name: string
  subtitle?: string
  emotion?: string
  original_emotion?: string
  scale?: number
  offset_x?: number
  offset_y?: number
  bubble_top?: number
  bubble_left?: number
  show?: boolean
  clothes_name?: string
  avatar_assets: Record<string, string>
  reference_audio_path: string | null
}

export interface A2DProjectManifest {
  format: typeof A2D_PROJECT_FORMAT
  schema_version: typeof A2D_PROJECT_SCHEMA_VERSION
  title: string
  exported_at: string
  roles: A2DProjectRole[]
  script: {
    project_name: string
    lines: Array<Record<string, unknown>>
    stages: Array<{ id: string; default_background: string | null }>
  }
  resources: A2DProjectResource[]
}

export interface ProjectValidationResult {
  ok: boolean
  error?: string
}

const ASSET_DIRECTORY_BY_KIND: Record<A2DProjectAssetKind, string> = {
  line_audio: 'audio',
  background: 'backgrounds',
  image: 'images',
  music: 'music',
  reference_audio: 'references',
  avatar: 'avatars',
}

const SAFE_ROLE_KEY = /^[A-Za-z0-9_-]{1,64}$/
const SAFE_ASSET_NAME = /^[a-z0-9][a-z0-9._-]{0,127}$/
const ALLOWED_GSV_PARAMETER_KEYS = new Set(['speed_factor', 'top_k', 'top_p', 'temperature'])
const ALLOWED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp', 'image/avif'])
const ALLOWED_AUDIO_TYPES = new Set([
  'audio/wav', 'audio/mpeg', 'audio/ogg', 'audio/flac', 'audio/mp4', 'audio/webm',
])

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function isFiniteNumber(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value)
}

function validateResourcePath(path: unknown, kind: A2DProjectAssetKind, field: string): string | null {
  if (typeof path !== 'string' || path.includes('\\') || path.includes(':') || path.startsWith('/')) {
    return `${field}: 必须是规范的项目相对路径`
  }
  const parts = path.split('/')
  if (parts.length !== 3 || parts[0] !== 'assets' || parts[1] !== ASSET_DIRECTORY_BY_KIND[kind]) {
    return `${field}: 路径类别与资源类型不一致`
  }
  if (parts.some(part => part === '' || part === '.' || part === '..') || !SAFE_ASSET_NAME.test(parts[2])) {
    return `${field}: 包含不安全的路径片段`
  }
  return null
}

function validateMediaType(resource: A2DProjectResource, field: string): string | null {
  if (resource.kind === 'line_audio' || resource.kind === 'reference_audio') {
    if (resource.media_type !== 'audio/wav') return `${field}.media_type: WAV 资源必须是 audio/wav`
    return null
  }
  if (resource.kind === 'background' || resource.kind === 'image' || resource.kind === 'avatar') {
    if (!ALLOWED_IMAGE_TYPES.has(resource.media_type)) return `${field}.media_type: 不支持的图片类型`
    return null
  }
  if (!ALLOWED_AUDIO_TYPES.has(resource.media_type)) return `${field}.media_type: 不支持的音乐类型`
  return null
}

/** Validate the portable v2 manifest before it is converted to runtime snapshots. */
export function validateProjectManifest(raw: unknown): ProjectValidationResult {
  if (!isRecord(raw)) return { ok: false, error: 'project.json: 必须是 JSON 对象' }
  if (raw.format !== A2D_PROJECT_FORMAT) return { ok: false, error: 'format: 不支持的 A2D 项目格式' }
  if (raw.schema_version !== A2D_PROJECT_SCHEMA_VERSION) {
    return { ok: false, error: 'schema_version: 只支持 A2D 项目 v2' }
  }
  if (typeof raw.title !== 'string' || !raw.title.trim()) return { ok: false, error: 'title: 标题不能为空' }
  if (typeof raw.exported_at !== 'string' || Number.isNaN(Date.parse(raw.exported_at))) {
    return { ok: false, error: 'exported_at: 必须是有效时间' }
  }
  if (!Array.isArray(raw.roles)) return { ok: false, error: 'roles: 必须是数组' }
  if (!isRecord(raw.script) || !Array.isArray(raw.script.lines) || !Array.isArray(raw.script.stages)) {
    return { ok: false, error: 'script: 缺少 lines 或 stages' }
  }
  if (typeof raw.script.project_name !== 'string') return { ok: false, error: 'script.project_name: 必须是字符串' }
  if (!Array.isArray(raw.resources)) return { ok: false, error: 'resources: 必须是数组' }
  if (raw.resources.length > A2D_PROJECT_MAX_ENTRIES - 1) return { ok: false, error: 'resources: 项目资源数量超过限制' }

  const rolesByKey = new Map<string, Record<string, unknown>>()
  for (let index = 0; index < raw.roles.length; index += 1) {
    const role = raw.roles[index]
    if (!isRecord(role) || typeof role.script_role_key !== 'string' || !SAFE_ROLE_KEY.test(role.script_role_key)) {
      return { ok: false, error: `roles[${index}].script_role_key: 角色键格式错误` }
    }
    if (rolesByKey.has(role.script_role_key)) return { ok: false, error: `roles[${index}].script_role_key: 角色键重复` }
    if (typeof role.display_name !== 'string' || !isRecord(role.avatar_assets)) {
      return { ok: false, error: `roles[${index}]: 缺少 display_name 或 avatar_assets` }
    }
    if (role.reference_audio_path !== null && typeof role.reference_audio_path !== 'string') {
      return { ok: false, error: `roles[${index}].reference_audio_path: 必须是资源路径或 null` }
    }
    rolesByKey.set(role.script_role_key, role)
  }

  const resourcesByPath = new Map<string, A2DProjectResource>()
  let declaredExpandedBytes = 0
  for (let index = 0; index < raw.resources.length; index += 1) {
    const value = raw.resources[index]
    const field = `resources[${index}]`
    if (!isRecord(value) || typeof value.kind !== 'string' || !Object.hasOwn(ASSET_DIRECTORY_BY_KIND, value.kind)) {
      return { ok: false, error: `${field}.kind: 未知资源类型` }
    }
    const resource = value as unknown as A2DProjectResource
    const pathError = validateResourcePath(resource.path, resource.kind, `${field}.path`)
    if (pathError) return { ok: false, error: pathError }
    if (resourcesByPath.has(resource.path)) return { ok: false, error: `${field}.path: 资源路径重复` }
    if (typeof resource.media_type !== 'string' || !Number.isSafeInteger(resource.byte_length) || resource.byte_length <= 0) {
      return { ok: false, error: `${field}: 媒体类型或字节数无效` }
    }
    if (resource.byte_length > A2D_PROJECT_MAX_ENTRY_BYTES) return { ok: false, error: `${field}.byte_length: 单个资源超过限制` }
    const mediaTypeError = validateMediaType(resource, field)
    if (mediaTypeError) return { ok: false, error: mediaTypeError }
    declaredExpandedBytes += resource.byte_length
    if (declaredExpandedBytes > A2D_PROJECT_MAX_EXPANDED_BYTES) return { ok: false, error: 'resources: 解压总大小超过限制' }
    resourcesByPath.set(resource.path, resource)
  }

  const usedResourcePaths = new Set<string>()
  const validateReference = (path: unknown, kind: A2DProjectAssetKind, field: string): string | null => {
    if (path === null || path === '') return null
    const pathError = validateResourcePath(path, kind, field)
    if (pathError) return pathError
    const resource = resourcesByPath.get(path as string)
    if (!resource || resource.kind !== kind) return `${field}: 引用了未声明的项目资源`
    usedResourcePaths.add(path as string)
    return null
  }

  for (let index = 0; index < raw.roles.length; index += 1) {
    const role = raw.roles[index] as Record<string, unknown>
    if (role.reference_audio_path !== null) {
      const error = validateReference(role.reference_audio_path, 'reference_audio', `roles[${index}].reference_audio_path`)
      if (error) return { ok: false, error }
    }
    for (const [emotion, path] of Object.entries(role.avatar_assets as Record<string, unknown>)) {
      const error = validateReference(path, 'avatar', `roles[${index}].avatar_assets.${emotion}`)
      if (error) return { ok: false, error }
    }
  }

  for (let index = 0; index < raw.script.lines.length; index += 1) {
    const line = raw.script.lines[index]
    if (!isRecord(line) || typeof line.id !== 'string' || typeof line.speaker !== 'string'
      || typeof line.display_text !== 'string' || typeof line.tts_text !== 'string'
      || !isFiniteNumber(line.index) || typeof line.stage_id !== 'string') {
      return { ok: false, error: `script.lines[${index}]: 台词结构不完整` }
    }
    if (line.speaker !== 'narrator' && line.speaker && !rolesByKey.has(line.speaker)) {
      return { ok: false, error: `script.lines[${index}].speaker: 未知角色键` }
    }
    if (line.character_role_key != null && (typeof line.character_role_key !== 'string' || !rolesByKey.has(line.character_role_key))) {
      return { ok: false, error: `script.lines[${index}].character_role_key: 未知角色键` }
    }
    if (line.audio_path !== null) {
      const error = validateReference(line.audio_path, 'line_audio', `script.lines[${index}].audio_path`)
      if (error) return { ok: false, error }
    }
    if (line.overlay === null) continue
    if (!isRecord(line.overlay)) return { ok: false, error: `script.lines[${index}].overlay: 必须是对象或 null` }
    const overlay = line.overlay
    const backgroundError = validateReference(overlay.background, 'background', `script.lines[${index}].overlay.background`)
    if (backgroundError) return { ok: false, error: backgroundError }
    const musicError = validateReference(overlay.bgm, 'music', `script.lines[${index}].overlay.bgm`)
    if (musicError) return { ok: false, error: musicError }
    if (overlay.ref_audio_path != null) {
      const referenceError = validateReference(overlay.ref_audio_path, 'reference_audio', `script.lines[${index}].overlay.ref_audio_path`)
      if (referenceError) return { ok: false, error: referenceError }
    }
    if (!Array.isArray(overlay.image_overlays)) return { ok: false, error: `script.lines[${index}].overlay.image_overlays: 必须是数组` }
    for (let imageIndex = 0; imageIndex < overlay.image_overlays.length; imageIndex += 1) {
      const image = overlay.image_overlays[imageIndex]
      if (!isRecord(image)) return { ok: false, error: `script.lines[${index}].overlay.image_overlays[${imageIndex}]: 必须是对象` }
      const imageError = validateReference(image.path, 'image', `script.lines[${index}].overlay.image_overlays[${imageIndex}].path`)
      if (imageError) return { ok: false, error: imageError }
    }
    if (overlay.gsv_params != null) {
      if (!isRecord(overlay.gsv_params)) return { ok: false, error: `script.lines[${index}].overlay.gsv_params: 必须是对象或 null` }
      const unknownKey = Object.keys(overlay.gsv_params).find(key => !ALLOWED_GSV_PARAMETER_KEYS.has(key))
      if (unknownKey) return { ok: false, error: `script.lines[${index}].overlay.gsv_params.${unknownKey}: 不允许的参数` }
      if (Object.values(overlay.gsv_params).some(value => !isFiniteNumber(value))) {
        return { ok: false, error: `script.lines[${index}].overlay.gsv_params: 参数必须是有限数值` }
      }
    }
  }

  for (let index = 0; index < raw.script.stages.length; index += 1) {
    const stage = raw.script.stages[index]
    if (!isRecord(stage) || typeof stage.id !== 'string') return { ok: false, error: `script.stages[${index}]: 舞台结构无效` }
    const error = validateReference(stage.default_background, 'background', `script.stages[${index}].default_background`)
    if (error) return { ok: false, error }
  }

  const unusedPath = [...resourcesByPath.keys()].find(path => !usedResourcePaths.has(path))
  if (unusedPath) return { ok: false, error: `resources: 存在未引用资源 ${unusedPath}` }
  return { ok: true }
}
