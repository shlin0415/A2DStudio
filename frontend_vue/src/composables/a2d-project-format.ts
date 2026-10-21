export const A2D_PROJECT_FORMAT = 'a2d-studio-project'
export const A2D_PROJECT_SCHEMA_VERSION = 2
export const A2D_PROJECT_MAX_ARCHIVE_BYTES = 512 * 1024 * 1024
export const A2D_PROJECT_MAX_ENTRY_BYTES = 128 * 1024 * 1024
export const A2D_PROJECT_MAX_EXPANDED_BYTES = 512 * 1024 * 1024
export const A2D_PROJECT_MAX_ENTRIES = 1024
export const A2D_PROJECT_MAX_MANIFEST_BYTES = 10 * 1024 * 1024

export type A2DProjectAssetKind = 'line_audio' | 'background' | 'image' | 'music' | 'reference_audio' | 'avatar'

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

export interface A2DProjectTextOverlay {
  id: string
  text: string
  x: number
  y: number
  width: number
  font_size: number
  color: string
  opacity: number
  z: number
}

export interface A2DProjectImageOverlay {
  id: string
  path: string
  x: number
  y: number
  w: number
  h: number
  opacity: number
  z: number
}

export interface A2DProjectLine {
  id: string
  speaker: string
  emotion?: string
  display_text: string
  tts_text: string
  action?: string
  index: number
  batch_index?: number
  batch_total?: number
  audio_path: string | null
  overlay: {
    character_role_key?: string | null
    ref_audio_path?: string | null
    gsv_params?: Record<string, number> | null
    sprite_positions?: Record<string, { x: number; y: number; scale: number }> | null
    background: string | null
    text_overlays: A2DProjectTextOverlay[]
    image_overlays: A2DProjectImageOverlay[]
    bgm: string | null
    bgm_volume: number
    bgm_loop: boolean
  } | null
  stage_id: string
}

export interface A2DProjectManifest {
  format: typeof A2D_PROJECT_FORMAT
  schema_version: typeof A2D_PROJECT_SCHEMA_VERSION
  title: string
  exported_at: string
  roles: A2DProjectRole[]
  script: {
    project_name: string
    lines: A2DProjectLine[]
    stages: Array<{ id: string; default_background: string | null }>
  }
  resources: A2DProjectResource[]
}

export type ProjectValidationResult = { ok: true } | { ok: false; error: string }

const ASSET_DIRECTORY_BY_KIND: Record<A2DProjectAssetKind, string> = {
  line_audio: 'audio',
  background: 'backgrounds',
  image: 'images',
  music: 'music',
  reference_audio: 'references',
  avatar: 'avatars',
}

const ALLOWED_ROLE_KEYS = new Set([
  'script_role_key', 'display_name', 'subtitle', 'emotion', 'original_emotion', 'scale',
  'offset_x', 'offset_y', 'bubble_top', 'bubble_left', 'show', 'clothes_name',
  'avatar_assets', 'reference_audio_path',
])
const ALLOWED_LINE_KEYS = new Set([
  'id', 'speaker', 'emotion', 'display_text', 'tts_text', 'action', 'index',
  'batch_index', 'batch_total', 'audio_path', 'overlay', 'stage_id',
])
const ALLOWED_OVERLAY_KEYS = new Set([
  'character_role_key', 'ref_audio_path', 'gsv_params', 'sprite_positions', 'background',
  'text_overlays', 'image_overlays', 'bgm', 'bgm_volume', 'bgm_loop',
])
const ALLOWED_GSV_PARAMETER_KEYS = new Set(['speed_factor', 'top_k', 'top_p', 'temperature'])
const ALLOWED_IMAGE_TYPES = new Set(['image/png', 'image/jpeg', 'image/gif', 'image/webp', 'image/bmp', 'image/avif'])
const ALLOWED_AUDIO_TYPES = new Set(['audio/wav', 'audio/mpeg', 'audio/ogg', 'audio/flac', 'audio/mp4', 'audio/webm'])
const SAFE_ROLE_KEY = /^[A-Za-z0-9_-]{1,64}$/
const SAFE_ASSET_NAME = /^[a-z0-9][a-z0-9._-]{0,127}$/

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: Set<string>, field: string): string | null {
  const key = Object.keys(value).find((name) => !allowed.has(name))
  return key ? `${field}.${key}: 不允许的字段` : null
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
  const filename = parts[2]
  if (parts.some((part) => part === '' || part === '.' || part === '..') || !filename || !SAFE_ASSET_NAME.test(filename)) {
    return `${field}: 包含不安全的路径片段`
  }
  return null
}

function validateResource(resource: unknown, index: number): ProjectValidationResult {
  const field = `resources[${index}]`
  if (!isRecord(resource)) return { ok: false, error: `${field}: 必须是对象` }
  const kinds = Object.keys(ASSET_DIRECTORY_BY_KIND) as A2DProjectAssetKind[]
  if (!kinds.includes(resource.kind as A2DProjectAssetKind)) return { ok: false, error: `${field}.kind: 未知资源类型` }
  const fieldError = hasOnlyKeys(resource, new Set(['path', 'kind', 'media_type', 'byte_length']), field)
  if (fieldError) return { ok: false, error: fieldError }
  const kind = resource.kind as A2DProjectAssetKind
  const pathError = validateResourcePath(resource.path, kind, `${field}.path`)
  if (pathError) return { ok: false, error: pathError }
  if (typeof resource.media_type !== 'string' || !Number.isSafeInteger(resource.byte_length) || (resource.byte_length as number) <= 0) {
    return { ok: false, error: `${field}: 媒体类型或字节数无效` }
  }
  if ((resource.byte_length as number) > A2D_PROJECT_MAX_ENTRY_BYTES) return { ok: false, error: `${field}.byte_length: 单个资源超过限制` }
  if ((kind === 'line_audio' || kind === 'reference_audio') && resource.media_type !== 'audio/wav') {
    return { ok: false, error: `${field}.media_type: WAV 资源必须是 audio/wav` }
  }
  if ((kind === 'background' || kind === 'image' || kind === 'avatar') && !ALLOWED_IMAGE_TYPES.has(resource.media_type)) {
    return { ok: false, error: `${field}.media_type: 不支持的图片类型` }
  }
  if (kind === 'music' && !ALLOWED_AUDIO_TYPES.has(resource.media_type)) {
    return { ok: false, error: `${field}.media_type: 不支持的音乐类型` }
  }
  return { ok: true }
}

function validateRole(role: unknown, index: number, roleKeys: Set<string>): ProjectValidationResult {
  const field = `roles[${index}]`
  if (!isRecord(role)) return { ok: false, error: `${field}: 必须是对象` }
  const unknownField = hasOnlyKeys(role, ALLOWED_ROLE_KEYS, field)
  if (unknownField) return { ok: false, error: unknownField }
  if (typeof role.script_role_key !== 'string' || !SAFE_ROLE_KEY.test(role.script_role_key)) {
    return { ok: false, error: `${field}.script_role_key: 角色键格式错误` }
  }
  if (roleKeys.has(role.script_role_key)) return { ok: false, error: `${field}.script_role_key: 角色键重复` }
  roleKeys.add(role.script_role_key)
  if (typeof role.display_name !== 'string' || !isRecord(role.avatar_assets)) {
    return { ok: false, error: `${field}: 缺少 display_name 或 avatar_assets` }
  }
  for (const property of ['subtitle', 'emotion', 'original_emotion', 'clothes_name']) {
    if (role[property] !== undefined && typeof role[property] !== 'string') return { ok: false, error: `${field}.${property}: 必须是字符串` }
  }
  if (role.reference_audio_path !== null && typeof role.reference_audio_path !== 'string') {
    return { ok: false, error: `${field}.reference_audio_path: 必须是资源路径或 null` }
  }
  for (const property of ['scale', 'offset_x', 'offset_y', 'bubble_top', 'bubble_left']) {
    if (role[property] !== undefined && !isFiniteNumber(role[property])) return { ok: false, error: `${field}.${property}: 必须是有限数值` }
  }
  if (role.show !== undefined && typeof role.show !== 'boolean') return { ok: false, error: `${field}.show: 必须是布尔值` }
  if (role.clothes_name !== undefined && typeof role.clothes_name !== 'string') return { ok: false, error: `${field}.clothes_name: 必须是字符串` }
  return { ok: true }
}

function validateOverlay(
  overlay: unknown,
  field: string,
  roleKeys: Set<string>,
  validateReference: (path: unknown, kind: A2DProjectAssetKind, field: string) => string | null,
): ProjectValidationResult {
  if (overlay === null) return { ok: true }
  if (!isRecord(overlay)) return { ok: false, error: `${field}: 必须是对象或 null` }
  const unknownField = hasOnlyKeys(overlay, ALLOWED_OVERLAY_KEYS, field)
  if (unknownField) return { ok: false, error: unknownField }
  if ((overlay.background !== null && typeof overlay.background !== 'string')
    || (overlay.bgm !== null && typeof overlay.bgm !== 'string')
    || !isFiniteNumber(overlay.bgm_volume) || typeof overlay.bgm_loop !== 'boolean') {
    return { ok: false, error: `${field}: 背景音乐或背景字段结构无效` }
  }
  if (overlay.character_role_key != null && (typeof overlay.character_role_key !== 'string' || !roleKeys.has(overlay.character_role_key))) {
    return { ok: false, error: `${field}.character_role_key: 未知角色键` }
  }
  for (const property of ['ref_audio_path', 'background', 'bgm']) {
    if (overlay[property] !== undefined && overlay[property] !== null && typeof overlay[property] !== 'string') {
      return { ok: false, error: `${field}.${property}: 必须是资源路径或 null` }
    }
  }
  for (const [name, kind] of [['ref_audio_path', 'reference_audio'], ['background', 'background'], ['bgm', 'music']] as const) {
    const pathError = validateReference(overlay[name], kind, `${field}.${name}`)
    if (pathError) return { ok: false, error: pathError }
  }
  if (!Array.isArray(overlay.text_overlays) || !Array.isArray(overlay.image_overlays)) {
    return { ok: false, error: `${field}: text_overlays 和 image_overlays 必须是数组` }
  }
  const textError = validateTextOverlays(overlay.text_overlays, `${field}.text_overlays`)
  if (textError) return { ok: false, error: textError }
  const imageError = validateImageOverlays(overlay.image_overlays, `${field}.image_overlays`, validateReference)
  if (imageError) return { ok: false, error: imageError }
  const spriteError = validateSpritePositions(overlay.sprite_positions, `${field}.sprite_positions`, roleKeys)
  if (spriteError) return { ok: false, error: spriteError }
  const gsvError = validateGsvParameters(overlay.gsv_params, `${field}.gsv_params`)
  if (gsvError) return { ok: false, error: gsvError }
  if (overlay.bgm_volume !== undefined && !isFiniteNumber(overlay.bgm_volume)) return { ok: false, error: `${field}.bgm_volume: 必须是有限数值` }
  if (overlay.bgm_loop !== undefined && typeof overlay.bgm_loop !== 'boolean') return { ok: false, error: `${field}.bgm_loop: 必须是布尔值` }
  return { ok: true }
}

function validateTextOverlays(overlays: unknown[], field: string): string | null {
  const allowed = new Set(['id', 'text', 'x', 'y', 'width', 'font_size', 'color', 'opacity', 'z'])
  for (let index = 0; index < overlays.length; index += 1) {
    const item = overlays[index]
    if (!isRecord(item)) return `${field}[${index}]: 必须是对象`
    const unknown = hasOnlyKeys(item, allowed, `${field}[${index}]`)
    if (unknown) return unknown
    if (typeof item.id !== 'string' || typeof item.text !== 'string' || typeof item.color !== 'string'
      || ['x', 'y', 'width', 'font_size', 'opacity', 'z'].some((name) => !isFiniteNumber(item[name]))) {
      return `${field}[${index}]: 文字覆盖结构无效`
    }
  }
  return null
}

function validateImageOverlays(
  overlays: unknown[],
  field: string,
  validateReference: (path: unknown, kind: A2DProjectAssetKind, field: string) => string | null,
): string | null {
  const allowed = new Set(['id', 'path', 'x', 'y', 'w', 'h', 'opacity', 'z'])
  for (let index = 0; index < overlays.length; index += 1) {
    const item = overlays[index]
    if (!isRecord(item)) return `${field}[${index}]: 必须是对象`
    const unknown = hasOnlyKeys(item, allowed, `${field}[${index}]`)
    if (unknown) return unknown
    if (typeof item.id !== 'string' || typeof item.path !== 'string' || !item.path
      || ['x', 'y', 'w', 'h', 'opacity', 'z'].some((name) => !isFiniteNumber(item[name]))) {
      return `${field}[${index}]: 图片覆盖结构无效`
    }
    const pathError = validateReference(item.path, 'image', `${field}[${index}].path`)
    if (pathError) return pathError
  }
  return null
}

function validateSpritePositions(value: unknown, field: string, roleKeys: Set<string>): string | null {
  if (value == null) return null
  if (!isRecord(value)) return `${field}: 必须是对象或 null`
  for (const [roleKey, position] of Object.entries(value)) {
    if (!roleKeys.has(roleKey)) return `${field}.${roleKey}: 未知角色键`
    if (!isRecord(position) || ['x', 'y', 'scale'].some((name) => !isFiniteNumber(position[name]))) {
      return `${field}.${roleKey}: 位置结构无效`
    }
    const unknown = hasOnlyKeys(position, new Set(['x', 'y', 'scale']), `${field}.${roleKey}`)
    if (unknown) return unknown
  }
  return null
}

function validateGsvParameters(value: unknown, field: string): string | null {
  if (value == null) return null
  if (!isRecord(value)) return `${field}: 必须是对象或 null`
  const unknown = Object.keys(value).find((key) => !ALLOWED_GSV_PARAMETER_KEYS.has(key))
  if (unknown) return `${field}.${unknown}: 不允许的参数`
  if (Object.values(value).some((parameter) => !isFiniteNumber(parameter))) return `${field}: 参数必须是有限数值`
  return null
}

function validateLine(
  line: unknown,
  index: number,
  roleKeys: Set<string>,
  validateReference: (path: unknown, kind: A2DProjectAssetKind, field: string) => string | null,
): ProjectValidationResult {
  const field = `script.lines[${index}]`
  if (!isRecord(line)) return { ok: false, error: `${field}: 必须是对象` }
  const unknownField = hasOnlyKeys(line, ALLOWED_LINE_KEYS, field)
  if (unknownField) return { ok: false, error: unknownField }
  if (typeof line.id !== 'string' || typeof line.speaker !== 'string' || !line.speaker || typeof line.display_text !== 'string'
    || typeof line.tts_text !== 'string' || !isFiniteNumber(line.index) || typeof line.stage_id !== 'string'
    || (line.audio_path !== null && typeof line.audio_path !== 'string')) {
    return { ok: false, error: `${field}: 台词结构不完整` }
  }
  if (line.emotion !== undefined && typeof line.emotion !== 'string') return { ok: false, error: `${field}.emotion: 必须是字符串` }
  if (line.action !== undefined && typeof line.action !== 'string') return { ok: false, error: `${field}.action: 必须是字符串` }
  for (const name of ['batch_index', 'batch_total']) {
    if (line[name] !== undefined && !Number.isSafeInteger(line[name])) return { ok: false, error: `${field}.${name}: 必须是整数` }
  }
  if (line.speaker !== 'narrator' && line.speaker && !roleKeys.has(line.speaker)) return { ok: false, error: `${field}.speaker: 未知角色键` }
  const audioError = validateReference(line.audio_path, 'line_audio', `${field}.audio_path`)
  if (audioError) return { ok: false, error: audioError }
  return validateOverlay(line.overlay, `${field}.overlay`, roleKeys, validateReference)
}

function validateStage(stage: unknown, index: number, validateReference: (path: unknown, kind: A2DProjectAssetKind, field: string) => string | null): ProjectValidationResult {
  const field = `script.stages[${index}]`
  if (!isRecord(stage) || Object.keys(stage).some((key) => !['id', 'default_background'].includes(key))
    || typeof stage.id !== 'string' || (stage.default_background !== null && typeof stage.default_background !== 'string')) {
    return { ok: false, error: `${field}: 舞台结构无效` }
  }
  const error = validateReference(stage.default_background, 'background', `${field}.default_background`)
  return error ? { ok: false, error } : { ok: true }
}

/** Validate the portable v2 manifest before it is converted to runtime snapshots. */
export function validateProjectManifest(raw: unknown): ProjectValidationResult {
  if (!isRecord(raw)) return { ok: false, error: 'project.json: 必须是 JSON 对象' }
  const topLevelError = hasOnlyKeys(raw, new Set(['format', 'schema_version', 'title', 'exported_at', 'roles', 'script', 'resources']), 'project.json')
  if (topLevelError) return { ok: false, error: topLevelError }
  if (raw.format !== A2D_PROJECT_FORMAT) return { ok: false, error: 'format: 不支持的 A2D 项目格式' }
  if (raw.schema_version !== A2D_PROJECT_SCHEMA_VERSION) return { ok: false, error: 'schema_version: 只支持 A2D 项目 v2' }
  if (typeof raw.title !== 'string' || !raw.title.trim()) return { ok: false, error: 'title: 标题不能为空' }
  if (typeof raw.exported_at !== 'string' || Number.isNaN(Date.parse(raw.exported_at))) return { ok: false, error: 'exported_at: 必须是有效时间' }
  if (!Array.isArray(raw.roles) || !Array.isArray(raw.resources)) return { ok: false, error: 'roles 或 resources: 必须是数组' }
  if (!isRecord(raw.script) || Object.keys(raw.script).some((key) => !['project_name', 'lines', 'stages'].includes(key))
    || !Array.isArray(raw.script.lines) || !Array.isArray(raw.script.stages) || typeof raw.script.project_name !== 'string') {
    return { ok: false, error: 'script: project_name、lines 或 stages 结构无效' }
  }
  if (raw.resources.length > A2D_PROJECT_MAX_ENTRIES - 1) return { ok: false, error: 'resources: 项目资源数量超过限制' }

  const roleKeys = new Set<string>()
  for (let index = 0; index < raw.roles.length; index += 1) {
    const result = validateRole(raw.roles[index], index, roleKeys)
    if (!result.ok) return result
  }
  const resourceState = validateResources(raw.resources)
  if (!resourceState.ok) return resourceState
  const usedPaths = new Set<string>()
  const validateReference = createReferenceValidator(resourceState.byPath, usedPaths)
  for (let index = 0; index < raw.roles.length; index += 1) {
    const result = validateRoleReferences(raw.roles[index], index, validateReference)
    if (!result.ok) return result
  }
  for (let index = 0; index < raw.script.lines.length; index += 1) {
    const result = validateLine(raw.script.lines[index], index, roleKeys, validateReference)
    if (!result.ok) return result
  }
  for (let index = 0; index < raw.script.stages.length; index += 1) {
    const result = validateStage(raw.script.stages[index], index, validateReference)
    if (!result.ok) return result
  }
  const unusedPath = [...resourceState.byPath.keys()].find((path) => !usedPaths.has(path))
  return unusedPath ? { ok: false, error: `resources: 存在未引用资源 ${unusedPath}` } : { ok: true }
}

function validateResources(resources: unknown[]): { ok: true; byPath: Map<string, A2DProjectResource> } | { ok: false; error: string } {
  const byPath = new Map<string, A2DProjectResource>()
  let expandedBytes = 0
  for (let index = 0; index < resources.length; index += 1) {
    const result = validateResource(resources[index], index)
    if (!result.ok) return result
    const resource = resources[index] as A2DProjectResource
    if (byPath.has(resource.path)) return { ok: false, error: `resources[${index}].path: 资源路径重复` }
    expandedBytes += resource.byte_length
    if (expandedBytes > A2D_PROJECT_MAX_EXPANDED_BYTES) return { ok: false, error: 'resources: 解压总大小超过限制' }
    byPath.set(resource.path, resource)
  }
  return { ok: true, byPath }
}

function createReferenceValidator(
  resources: Map<string, A2DProjectResource>,
  usedPaths: Set<string>,
): (path: unknown, kind: A2DProjectAssetKind, field: string) => string | null {
  return (path, kind, field) => {
    if (path === null || path === undefined) return null
    const pathError = validateResourcePath(path, kind, field)
    if (pathError) return pathError
    const resource = resources.get(path as string)
    if (!resource || resource.kind !== kind) return `${field}: 引用了未声明的项目资源`
    usedPaths.add(path as string)
    return null
  }
}

function validateRoleReferences(
  value: unknown,
  index: number,
  validateReference: (path: unknown, kind: A2DProjectAssetKind, field: string) => string | null,
): ProjectValidationResult {
  const role = value as Record<string, unknown>
  const referenceError = validateReference(role.reference_audio_path, 'reference_audio', `roles[${index}].reference_audio_path`)
  if (referenceError) return { ok: false, error: referenceError }
  const avatarAssets = role.avatar_assets as Record<string, unknown>
  for (const [emotion, path] of Object.entries(avatarAssets)) {
    if (!/^[\p{L}\p{N}_-]{1,64}$/u.test(emotion) || typeof path !== 'string' || !path) {
      return { ok: false, error: `roles[${index}].avatar_assets.${emotion}: 头像资源引用无效` }
    }
    const error = validateReference(path, 'avatar', `roles[${index}].avatar_assets.${emotion}`)
    if (error) return { ok: false, error }
  }
  return { ok: true }
}

/** Add a chunk size to an import counter without allocating a buffer for limit tests. */
export function nextProjectByteCount(current: number, increment: number, limit: number, field: string): number {
  if (!Number.isSafeInteger(current) || current < 0 || !Number.isSafeInteger(increment) || increment < 0) {
    throw new RangeError(`${field}: byte counter is invalid`)
  }
  const next = current + increment
  if (!Number.isSafeInteger(next) || next > limit) throw new RangeError(`${field}: size limit exceeded`)
  return next
}
