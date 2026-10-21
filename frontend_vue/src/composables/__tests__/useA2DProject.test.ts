import { validateProjectManifest } from '@/composables/a2d-project-format'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { strFromU8, unzipSync, zipSync } from 'fflate'
import { useScriptStore, type LineOverlay, type ScriptLine } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import { buildExportEnvelope, type ExportEnvelope } from '@/composables/useA2DSaveLoad'
import type { GameRole } from '@/stores/modules/game/state'
import { exportA2DProject, packA2DProject, unpackA2DProject } from '@/composables/useA2DProject'
import {
  getImportedProjectAvatar,
  registerImportedProjectAssets,
} from '@/composables/a2d-project-runtime-assets'
import {
  A2D_PROJECT_MAX_ARCHIVE_BYTES,
  A2D_PROJECT_MAX_ENTRY_BYTES,
  A2D_PROJECT_MAX_EXPANDED_BYTES,
  nextProjectByteCount,
} from '@/composables/a2d-project-format'

function makeLine(id: string, audioPath: string | null): ScriptLine {
  return {
    id,
    speaker: 'ema',
    display_text: '早上好。',
    tts_text: '早上好。',
    index: 0,
    audio_path: audioPath,
    overlay: null,
    stage_id: '',
  }
}

beforeEach(() => setActivePinia(createPinia()))
afterEach(() => vi.unstubAllGlobals())

if (!File.prototype.stream) {
  Object.defineProperty(File.prototype, 'stream', {
    configurable: true,
    value: function stream(this: File) {
      return new ReadableStream<Uint8Array>({
        start: async (controller) => {
          controller.enqueue(new Uint8Array(await this.arrayBuffer()))
          controller.close()
        },
      })
    },
  })
}

describe('A2D project archive', () => {
  it('packages a v2 script and line audio under relative paths', async () => {
    const envelope = buildExportEnvelope()
    envelope.script.lines = [makeLine('line-1', '/audio/a2d_line-1.wav')]
    envelope.script.lines[0].speaker = 'narrator'
    envelope.script.projectName = '双人短剧'
    const audioBytes = new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69])
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(audioBytes, {
      headers: { 'Content-Type': 'audio/wav' },
    })))

    const archive = await packA2DProject(envelope, '双人短剧')
    const files = unzipSync(archive)
    const manifest = JSON.parse(strFromU8(files['project.json']))

    expect(manifest.title).toBe('双人短剧')
    expect(manifest.schema_version).toBe(2)
    expect(manifest.script.lines[0].audio_path).toBe('assets/audio/line-0001.wav')
    expect(Array.from(files['assets/audio/line-0001.wav'])).toEqual(Array.from(audioBytes))
    expect(strFromU8(files['project.json'])).not.toContain('CHAT_API_KEY')
  })

  it('rejects v1 archives without changing the current project', async () => {
    const envelope = buildExportEnvelope()
    envelope.script.lines = [makeLine('line-1', 'assets/audio/line-0001.wav')]
    envelope.script.projectName = '短剧'
    const manifest = {
      format: 'a2d-studio-project',
      version: 1,
      title: '短剧',
      exportedAt: '2026-10-18T00:00:00Z',
      envelope,
    }
    const archive = zipSync({
      'project.json': new TextEncoder().encode(JSON.stringify(manifest)),
      'assets/audio/line-0001.wav': new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69]),
    })
    useScriptStore().projectName = '原项目'
    useScriptStore().lines = [makeLine('existing', null)]

    const result = await unpackA2DProject(new File([archive], 'short.a2d.zip'))

    expect(result.ok).toBe(false)
    expect(result.error).toContain('v2')
    expect(useScriptStore().projectName).toBe('原项目')
    expect(useScriptStore().lines[0].id).toBe('existing')
  })

  it('keeps the exported archive URL alive until the browser can start the download', async () => {
    const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    const createObjectURL = vi.fn(() => 'blob:a2d-export')
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', { configurable: true, value: createObjectURL })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    const click = vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(() => {})
    vi.useFakeTimers()
    useScriptStore().projectName = 'export-lifecycle'

    try {
      await exportA2DProject()

      expect(click).toHaveBeenCalledOnce()
      expect(revokeObjectURL).not.toHaveBeenCalled()

      await vi.advanceTimersByTimeAsync(1000)
      expect(revokeObjectURL).toHaveBeenCalledWith('blob:a2d-export')
    } finally {
      vi.useRealTimers()
      click.mockRestore()
      if (originalCreateObjectURL) Object.defineProperty(URL, 'createObjectURL', originalCreateObjectURL)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (originalRevokeObjectURL) Object.defineProperty(URL, 'revokeObjectURL', originalRevokeObjectURL)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })
})


function makeValidV2Manifest() {
  return {
    format: 'a2d-studio-project',
    schema_version: 2,
    title: '便携剧本',
    exported_at: '2026-10-22T00:00:00.000Z',
    roles: [{ script_role_key: 'ema', display_name: '艾玛', avatar_assets: {}, reference_audio_path: null }],
    script: {
      project_name: '便携剧本',
      lines: [{
        id: 'line-1', speaker: 'ema', emotion: '正常', display_text: '你好。',
        tts_text: '你好。', index: 0, audio_path: 'assets/audio/line-0001.wav', overlay: null, stage_id: '',
      }],
      stages: [],
    },
    resources: [{
      path: 'assets/audio/line-0001.wav',
      kind: 'line_audio',
      media_type: 'audio/wav',
      byte_length: 44,
    }],
  }
}

function listCentralDirectoryEntries(bytes: Uint8Array): Array<{ name: string; offset: number; localOffset: number }> {
  const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength)
  let endRecord = -1
  for (let offset = bytes.length - 22; offset >= 0; offset -= 1) {
    if (view.getUint32(offset, true) === 0x06054b50) {
      endRecord = offset
      break
    }
  }
  if (endRecord < 0) throw new Error('test archive has no EOCD')
  const count = view.getUint16(endRecord + 10, true)
  let cursor = view.getUint32(endRecord + 16, true)
  const entries: Array<{ name: string; offset: number; localOffset: number }> = []
  for (let index = 0; index < count; index += 1) {
    const nameLength = view.getUint16(cursor + 28, true)
    const extraLength = view.getUint16(cursor + 30, true)
    const commentLength = view.getUint16(cursor + 32, true)
    const name = new TextDecoder().decode(bytes.subarray(cursor + 46, cursor + 46 + nameLength))
    entries.push({ name, offset: cursor, localOffset: view.getUint32(cursor + 42, true) })
    cursor += 46 + nameLength + extraLength + commentLength
  }
  return entries
}

describe('A2D project v2 schema', () => {
  it('accepts a portable project with role keys and relative resources', () => {
    expect(validateProjectManifest(makeValidV2Manifest())).toEqual({ ok: true })
  })

  it('rejects an unsupported schema version with a field-specific error', () => {
    const manifest = makeValidV2Manifest()
    manifest.schema_version = 1

    const result = validateProjectManifest(manifest)

    expect(result.ok).toBe(false)
    expect(result.error).toContain('schema_version')
  })

  it('rejects runtime-only role identity fields', () => {
    const manifest = makeValidV2Manifest() as ReturnType<typeof makeValidV2Manifest> & { roles: Array<Record<string, unknown>> }
    manifest.roles[0].roleId = 101

    const result = validateProjectManifest(manifest)

    expect(result.ok).toBe(false)
    expect(result.error).toContain('roleId')
  })

  it('rejects a resource path that escapes the archive assets directory', () => {
    const manifest = makeValidV2Manifest()
    manifest.resources[0].path = 'assets/audio/../../secret.wav'

    const result = validateProjectManifest(manifest)

    expect(result.ok).toBe(false)
    expect(result.error).toContain('resources[0].path')
  })

  it('rejects a valid-looking resource path that is not declared', () => {
    const manifest = makeValidV2Manifest()
    manifest.script.lines[0].audio_path = 'assets/audio/not-declared.wav'

    const result = validateProjectManifest(manifest)

    expect(result.ok).toBe(false)
    expect(result.error).toContain('未声明')
  })
})


function makeExportRole(roleId: number, scriptRoleKey: string): GameRole {
  return Object.assign({
    roleId,
    roleName: scriptRoleKey,
    roleSubTitle: `${scriptRoleKey} subtitle`,
    thinkMessage: 'thinking',
    emotion: '正常',
    originalEmotion: '正常',
    scale: 1,
    offsetY: 0,
    offsetX: 0,
    bubbleTop: 5,
    bubbleLeft: 20,
    show: true,
    clothes: {},
    clothesName: 'default',
    bodyPart: {},
    character_folder: `D:\\local\\characters\\${scriptRoleKey}`,
  }, { scriptRoleKey })
}

function makeProjectOverlay(lineId: string, roleId: number): LineOverlay {
  return {
    line_id: lineId,
    character_id: roleId,
    ref_audio_path: `D:\\local\\characters\\role-${roleId}\\reference.wav`,
    gsv_params: { speed_factor: 1.1, gsv_api_url: 'http://127.0.0.1:31801', private_note: 'must-not-export' },
    sprite_positions: { ema: { x: 30, y: 60, scale: 1.1 } },
    background: '/api/v1/chat/script/background_file/night.webp',
    text_overlays: [],
    image_overlays: [{
      id: 'logo', path: '/api/v1/chat/script/pic_file/logo.png',
      x: 50, y: 15, w: 120, h: 40, opacity: 1, z: 2,
    }],
    bgm: '/api/v1/chat/back-music/music_file/night.mp3',
    bgm_volume: 0.4,
    bgm_loop: true,
  }
}

function makeExportEnvelope(): ExportEnvelope {
  const envelope = buildExportEnvelope()
  const ema = makeLine('line-ema', '/audio/a2d_line-ema.wav')
  const hiro = makeLine('line-hiro', '/audio/a2d_line-hiro.wav')
  ema.speaker = 'ema'
  ema.overlay = makeProjectOverlay(ema.id, 101)
  hiro.speaker = 'hiro'
  hiro.overlay = makeProjectOverlay(hiro.id, 202)
  envelope.script.projectName = '双人短剧'
  envelope.script.lines = [ema, hiro]
  envelope.game.gameRoles = {
    101: makeExportRole(101, 'ema'),
    202: makeExportRole(202, 'hiro'),
  }
  envelope.game.presentRoleIds = [101, 202]
  envelope.stages = [{ id: 'stage-night', default_background: '/api/v1/chat/script/background_file/night.webp' }]
  return envelope
}

function stubProjectAssetFetch(missingSpeaker?: string) {
  const wavBytes = new Uint8Array([82, 73, 70, 70, 0, 0, 0, 0, 87, 65, 86, 69])
  const imageBytes = new Uint8Array([137, 80, 78, 71, 13, 10, 26, 10, 0])
  const musicBytes = new Uint8Array([73, 68, 51, 0, 0, 0, 0, 0, 0, 0])
  const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input)
    if (missingSpeaker && url.includes(`/reference-audio/${missingSpeaker}`)) {
      return new Response(null, { status: 404 })
    }
    let bytes = imageBytes
    let mediaType = 'image/png'
    if (url.includes('/audio/a2d_line-') || url.includes('/reference-audio/')) {
      bytes = wavBytes
      mediaType = 'audio/wav'
    } else if (url.includes('music_file/')) {
      bytes = musicBytes
      mediaType = 'audio/mpeg'
    }
    return new Response(bytes, { status: 200, headers: { 'Content-Type': mediaType } })
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

describe('A2D project v2 export contract', () => {
  it('exports explicit project media without local role IDs, paths, or service settings', async () => {
    const fetchMock = stubProjectAssetFetch()
    const archive = await packA2DProject(makeExportEnvelope(), '双人短剧')
    const files = unzipSync(archive)
    const manifest = JSON.parse(strFromU8(files['project.json']))
    const manifestText = strFromU8(files['project.json'])

    expect(manifest.schema_version).toBe(2)
    expect(manifest.roles.map((role: { script_role_key: string }) => role.script_role_key)).toEqual(['ema', 'hiro'])
    expect(manifest.script.lines.map((line: { audio_path: string }) => line.audio_path)).toEqual([
      'assets/audio/line-0001.wav', 'assets/audio/line-0002.wav',
    ])
    expect(manifest.script.lines[0].overlay.background).toBe('assets/backgrounds/asset-0001.webp')
    expect(manifest.script.lines[0].overlay.image_overlays[0].path).toBe('assets/images/asset-0001.png')
    expect(manifest.script.lines[0].overlay.bgm).toBe('assets/music/asset-0001.mp3')
    expect(manifestText).not.toContain('roleId')
    expect(manifestText).not.toContain('character_folder')
    expect(manifestText).not.toContain('D:\\local')
    expect(manifestText).not.toContain('http://')
    expect(manifestText).not.toContain('/api/')
    expect(manifestText).not.toContain('reference.wav')
    expect(manifestText).not.toContain('gsv_api_url')
    expect(manifestText).not.toContain('private_note')
    expect(Object.keys(files).sort()).toEqual(['project.json', ...manifest.resources.map((resource: { path: string }) => resource.path)].sort())
    expect(Object.keys(files)).toEqual(expect.arrayContaining([
      'assets/references/asset-0001.wav',
      'assets/references/asset-0002.wav',
      'assets/avatars/asset-0001.png',
      'assets/avatars/asset-0002.png',
    ]))
    expect(fetchMock).toHaveBeenCalledTimes(9)
    expect(fetchMock.mock.calls.filter(([url]) => String(url).includes('background_file/'))).toHaveLength(1)
  })

  it('fails export when a referenced GSV WAV is unavailable', async () => {
    stubProjectAssetFetch('hiro')

    await expect(packA2DProject(makeExportEnvelope(), '双人短剧')).rejects.toThrow('hiro')
  })

  it('exports a stage-only background as a declared project resource', async () => {
    stubProjectAssetFetch()
    const envelope = makeExportEnvelope()
    envelope.stages[0]!.default_background = '/api/v1/chat/script/background_file/stage-only.png'

    const archive = await packA2DProject(envelope, '双人短剧')
    const files = unzipSync(archive)
    const manifest = JSON.parse(strFromU8(files['project.json']))
    const stageBackgroundPath = manifest.script.stages[0].default_background

    expect(stageBackgroundPath).toBe('assets/backgrounds/asset-0002.png')
    expect(manifest.resources).toContainEqual(expect.objectContaining({
      path: stageBackgroundPath,
      kind: 'background',
      media_type: 'image/png',
    }))
    expect(Array.from(files[stageBackgroundPath])).toEqual([137, 80, 78, 71, 13, 10, 26, 10, 0])
  })

  it('rejects unregistered Blob URLs for project media', async () => {
    registerImportedProjectAssets(new Map(), [])
    const envelope = makeExportEnvelope()
    envelope.script.lines[0]!.overlay!.background = 'blob:untrusted-background'
    stubProjectAssetFetch()

    await expect(packA2DProject(envelope, '双人短剧')).rejects.toThrow(
      '只允许使用已导入项目中的临时资源',
    )
  })
})

describe('A2D project v2 import contract', () => {
  it('re-exports a reopened project with the same referenced asset bytes', async () => {
    const localAssetFetch = stubProjectAssetFetch()
    const firstArchive = await packA2DProject(makeExportEnvelope(), '双人短剧')
    const firstEntries = unzipSync(firstArchive)
    const firstManifest = JSON.parse(strFromU8(firstEntries['project.json']))
    const importedBlobs = new Map<string, Blob>()
    const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    let nextUrl = 0
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn((blob: Blob) => {
        const url = `blob:roundtrip-${++nextUrl}`
        importedBlobs.set(url, blob)
        return url
      }),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })
    vi.stubGlobal(
      'fetch',
      vi.fn(async (input: RequestInfo | URL) => {
        const importedBlob = importedBlobs.get(String(input))
        if (importedBlob) {
          return new Response(new Uint8Array(await importedBlob.arrayBuffer()), {
            headers: { 'Content-Type': importedBlob.type },
          })
        }
        if (String(input).includes('/reference-audio/')) {
          return new Response(new Uint8Array([82, 73, 70, 70, 9, 9, 9, 9, 87, 65, 86, 69]), {
            headers: { 'Content-Type': 'audio/wav' },
          })
        }
        return localAssetFetch(input)
      }),
    )

    try {
      const imported = await unpackA2DProject(new File([firstArchive], 'short.a2d.zip'))
      expect(imported.ok).toBe(true)

      const secondArchive = await packA2DProject(buildExportEnvelope(), '双人短剧')
      const secondEntries = unzipSync(secondArchive)
      const secondManifest = JSON.parse(strFromU8(secondEntries['project.json']))
      expect(secondManifest.resources).toHaveLength(firstManifest.resources.length)
      for (let index = 0; index < firstManifest.resources.length; index += 1) {
        const firstResource = firstManifest.resources[index]
        const secondResource = secondManifest.resources[index]
        expect(secondResource.kind).toBe(firstResource.kind)
        expect(secondResource.media_type).toBe(firstResource.media_type)
        expect(Array.from(secondEntries[secondResource.path])).toEqual(
          Array.from(firstEntries[firstResource.path]),
        )
      }
    } finally {
      registerImportedProjectAssets(new Map(), [])
      if (originalCreateObjectURL) Object.defineProperty(URL, 'createObjectURL', originalCreateObjectURL)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (originalRevokeObjectURL) Object.defineProperty(URL, 'revokeObjectURL', originalRevokeObjectURL)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('restores bundled media as Blob URLs and builds local roles from stable keys', async () => {
    stubProjectAssetFetch()
    const archive = await packA2DProject(makeExportEnvelope(), '双人短剧')
    const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    let nextUrl = 0
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => `blob:project-import-${++nextUrl}`),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })

    try {
      const result = await unpackA2DProject(new File([archive], 'short.a2d.zip'))

      expect(result.ok).toBe(true)
      expect(useScriptStore().projectName).toBe('双人短剧')
    expect(useScriptStore().lines[0].audio_path).toMatch(/^blob:project-import-/)
      expect(useScriptStore().lines[0].overlay?.background).toMatch(/^blob:project-import-/)
      expect(useScriptStore().lines[0].overlay?.character_id).toBeLessThan(-1)
      expect(useScriptStore().stageMap['stage-night']).toMatch(/^blob:project-import-/)
      expect(useGameStore().presentRoleIds).toEqual([-1_000_000, -1_000_001])
      expect(useGameStore().gameRoles[-1_000_000].scriptRoleKey).toBe('ema')
      expect(getImportedProjectAvatar('ema', 'default', '正常')).toMatch(/^blob:project-import-/)
      expect(revokeObjectURL).not.toHaveBeenCalled()
    } finally {
      if (originalCreateObjectURL) Object.defineProperty(URL, 'createObjectURL', originalCreateObjectURL)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (originalRevokeObjectURL) Object.defineProperty(URL, 'revokeObjectURL', originalRevokeObjectURL)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('restores a background referenced only by the stage default', async () => {
    stubProjectAssetFetch()
    const envelope = makeExportEnvelope()
    envelope.stages[0]!.default_background = '/api/v1/chat/script/background_file/stage-only.png'
    const archive = await packA2DProject(envelope, '双人短剧')
    const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    const importedBlobs = new Map<string, Blob>()
    let nextUrl = 0
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn((blob: Blob) => {
        const url = `blob:stage-background-${++nextUrl}`
        importedBlobs.set(url, blob)
        return url
      }),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: vi.fn() })

    try {
      const result = await unpackA2DProject(new File([archive], 'stage-only-background.a2d.zip'))

      expect(result.ok).toBe(true)
      const stageBackgroundUrl = useScriptStore().stageMap['stage-night']
      const stageBackgroundBlob = importedBlobs.get(stageBackgroundUrl)
      expect(stageBackgroundUrl).toMatch(/^blob:stage-background-/)
      expect(stageBackgroundBlob?.type).toBe('image/png')
      expect(Array.from(new Uint8Array(await stageBackgroundBlob!.arrayBuffer()))).toEqual([
        137, 80, 78, 71, 13, 10, 26, 10, 0,
      ])
      expect(useScriptStore().lines[0]!.overlay?.background).not.toBe(stageBackgroundUrl)
    } finally {
      registerImportedProjectAssets(new Map(), [])
      if (originalCreateObjectURL) Object.defineProperty(URL, 'createObjectURL', originalCreateObjectURL)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (originalRevokeObjectURL) Object.defineProperty(URL, 'revokeObjectURL', originalRevokeObjectURL)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('rejects a corrupted central-directory CRC before changing stores', async () => {
    const manifest = makeValidV2Manifest()
    const files: Record<string, Uint8Array> = {
      'project.json': new TextEncoder().encode(JSON.stringify(manifest)),
      'assets/audio/line-0001.wav': new Uint8Array(44),
    }
    const archive = zipSync(files)
    const corrupted = archive.slice()
    const view = new DataView(corrupted.buffer, corrupted.byteOffset, corrupted.byteLength)
    const projectRecord = listCentralDirectoryEntries(corrupted).find((entry) => entry.name === 'project.json')!
    const corruptedChecksum = view.getUint32(projectRecord.offset + 16, true) ^ 1
    view.setUint32(projectRecord.offset + 16, corruptedChecksum, true)
    view.setUint32(projectRecord.localOffset + 14, corruptedChecksum, true)
    useScriptStore().projectName = '原项目'

    const result = await unpackA2DProject(new File([corrupted], 'corrupt.a2d.zip'))

    expect(result.ok).toBe(false)
    expect(result.error).toContain('CRC')
    expect(useScriptStore().projectName).toBe('原项目')
  })

  it('rejects archive path traversal before extracting entries', async () => {
    const archive = zipSync({ '../outside.txt': new Uint8Array([1]) })

    const result = await unpackA2DProject(new File([archive], 'unsafe.a2d.zip'))

    expect(result.ok).toBe(false)
    expect(result.error).toContain('非法路径')
  })

  it('rejects duplicate archive paths before extraction', async () => {
    const archive = zipSync({
      'assets/audio/line-0001.wav': new Uint8Array([1]),
      'assets/audio/line-0002.wav': new Uint8Array([2]),
    })
    const corrupted = archive.slice()
    const entries = listCentralDirectoryEntries(corrupted)
    const second = entries.find((entry) => entry.name.endsWith('line-0002.wav'))!
    const duplicate = new TextEncoder().encode('assets/audio/line-0001.wav')
    corrupted.set(duplicate, second.offset + 46)

    const result = await unpackA2DProject(new File([corrupted], 'duplicate.a2d.zip'))

    expect(result.ok).toBe(false)
    expect(result.error).toContain('重复路径')
  })

  it('rejects too many entries and oversized declared assets before decompression', async () => {
    const smallArchive = zipSync({
      'project.json': new Uint8Array([123, 125]),
      'assets/audio/line-0001.wav': new Uint8Array([1]),
    })
    const tooManyEntries = smallArchive.slice()
    const tooManyView = new DataView(tooManyEntries.buffer, tooManyEntries.byteOffset, tooManyEntries.byteLength)
    let endRecord = tooManyEntries.length - 22
    while (tooManyView.getUint32(endRecord, true) !== 0x06054b50) endRecord -= 1
    tooManyView.setUint16(endRecord + 8, 1025, true)
    tooManyView.setUint16(endRecord + 10, 1025, true)
    const countResult = await unpackA2DProject(new File([tooManyEntries], 'many.a2d.zip'))
    expect(countResult.error).toContain('条目数量')

    const oversized = smallArchive.slice()
    const oversizedView = new DataView(oversized.buffer, oversized.byteOffset, oversized.byteLength)
    const audioRecord = listCentralDirectoryEntries(oversized).find((entry) => entry.name.endsWith('.wav'))!
    oversizedView.setUint32(audioRecord.offset + 24, A2D_PROJECT_MAX_ENTRY_BYTES + 1, true)
    const sizeResult = await unpackA2DProject(new File([oversized], 'large-entry.a2d.zip'))
    expect(sizeResult.error).toContain('128 MiB')
  })

  it('rejects an oversized archive from its file size without reading it', async () => {
    const oversizedFile = { size: A2D_PROJECT_MAX_ARCHIVE_BYTES + 1 } as File

    const result = await unpackA2DProject(oversizedFile)

    expect(result.ok).toBe(false)
    expect(result.error).toContain('512 MiB')
  })

  it('rejects an oversized project.json from its central-directory length', async () => {
    const archive = zipSync({ 'project.json': new Uint8Array([123, 125]) })
    const corrupted = archive.slice()
    const view = new DataView(corrupted.buffer, corrupted.byteOffset, corrupted.byteLength)
    const projectRecord = listCentralDirectoryEntries(corrupted).find((entry) => entry.name === 'project.json')!
    view.setUint32(projectRecord.offset + 24, 10 * 1024 * 1024 + 1, true)

    const result = await unpackA2DProject(new File([corrupted], 'large-manifest.a2d.zip'))

    expect(result.ok).toBe(false)
    expect(result.error).toContain('10 MiB')
  })

  it('rejects a truncated archive', async () => {
    const archive = zipSync({ 'project.json': new Uint8Array([123, 125]) })
    const truncated = archive.slice(0, archive.length - 12)

    const result = await unpackA2DProject(new File([truncated], 'truncated.a2d.zip'))

    expect(result.ok).toBe(false)
    expect(result.error).toContain('结束目录')
  })

  it('revokes staged URLs and preserves the active project when import is phase-blocked', async () => {
    stubProjectAssetFetch()
    const archive = await packA2DProject(makeExportEnvelope(), '双人短剧')
    const originalCreateObjectURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    const originalRevokeObjectURL = Object.getOwnPropertyDescriptor(URL, 'revokeObjectURL')
    const createdUrls: string[] = []
    const revokeObjectURL = vi.fn()
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => {
        const url = `blob:rejected-${createdUrls.length + 1}`
        createdUrls.push(url)
        return url
      }),
    })
    Object.defineProperty(URL, 'revokeObjectURL', { configurable: true, value: revokeObjectURL })
    useScriptStore().projectName = '原项目'
    useScriptStore().lines = [makeLine('existing', null)]
    useScriptStore().phase = 'thinking'
    const activeAvatar = getImportedProjectAvatar('ema', 'default', '正常')

    try {
      const result = await unpackA2DProject(new File([archive], 'blocked.a2d.zip'))

      expect(result.ok).toBe(false)
      expect(result.error).toContain('暂停')
      expect(useScriptStore().projectName).toBe('原项目')
      expect(useScriptStore().lines[0].id).toBe('existing')
      expect(getImportedProjectAvatar('ema', 'default', '正常')).toBe(activeAvatar)
      expect(revokeObjectURL.mock.calls.map(([url]) => url)).toEqual(createdUrls)
    } finally {
      if (originalCreateObjectURL) Object.defineProperty(URL, 'createObjectURL', originalCreateObjectURL)
      else Reflect.deleteProperty(URL, 'createObjectURL')
      if (originalRevokeObjectURL) Object.defineProperty(URL, 'revokeObjectURL', originalRevokeObjectURL)
      else Reflect.deleteProperty(URL, 'revokeObjectURL')
    }
  })

  it('enforces byte limits with numeric accounting', () => {
    expect(nextProjectByteCount(A2D_PROJECT_MAX_EXPANDED_BYTES - 1, 1, A2D_PROJECT_MAX_EXPANDED_BYTES, 'test'))
      .toBe(A2D_PROJECT_MAX_EXPANDED_BYTES)
    expect(() => nextProjectByteCount(A2D_PROJECT_MAX_EXPANDED_BYTES, 1, A2D_PROJECT_MAX_EXPANDED_BYTES, 'test'))
      .toThrow('size limit exceeded')
  })
})
