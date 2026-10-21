import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { unzipSync } from 'fflate'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { buildExportEnvelope } from '@/composables/useA2DSaveLoad'
import {
  openA2DProjectFromDirectory,
  packA2DProject,
  saveA2DProjectToDirectory,
} from '@/composables/useA2DProject'

interface MemoryFile {
  bytes: Uint8Array
}

interface MemoryDirectory {
  entries: Map<string, MemoryDirectory | MemoryFile>
}

function createMemoryDirectory(): { node: MemoryDirectory; handle: FileSystemDirectoryHandle } {
  const node: MemoryDirectory = { entries: new Map() }

  function createHandle(directory: MemoryDirectory): FileSystemDirectoryHandle {
    return {
      async getDirectoryHandle(name: string, options?: FileSystemGetDirectoryOptions) {
        let entry = directory.entries.get(name)
        if (!entry && options?.create) {
          entry = { entries: new Map() }
          directory.entries.set(name, entry)
        }
        if (!entry || !('entries' in entry))
          throw new DOMException('Directory not found', 'NotFoundError')
        return createHandle(entry)
      },
      async getFileHandle(name: string, options?: FileSystemGetFileOptions) {
        let entry = directory.entries.get(name)
        if (!entry && options?.create) {
          entry = { bytes: new Uint8Array() }
          directory.entries.set(name, entry)
        }
        if (!entry || !('bytes' in entry)) throw new DOMException('File not found', 'NotFoundError')
        const file = entry
        return {
          async getFile() {
            const bytes = file.bytes.slice().buffer
            return new File([bytes], name)
          },
          async createWritable() {
            return {
              async write(value: FileSystemWriteChunkType) {
                if (value instanceof ArrayBuffer) file.bytes = new Uint8Array(value)
                else if (value instanceof Uint8Array) file.bytes = new Uint8Array(value)
                else throw new TypeError('Expected binary file content')
              },
              async close() {},
              async abort() {},
            } as unknown as FileSystemWritableFileStream
          },
        } as unknown as FileSystemFileHandle
      },
    } as unknown as FileSystemDirectoryHandle
  }

  return { node, handle: createHandle(node) }
}

function writeMemoryFile(root: MemoryDirectory, path: string, bytes: Uint8Array): void {
  const parts = path.split('/')
  let directory = root
  for (const part of parts.slice(0, -1)) {
    let entry = directory.entries.get(part)
    if (!entry) {
      entry = { entries: new Map() }
      directory.entries.set(part, entry)
    }
    if (!('entries' in entry)) throw new Error(`${part} is not a directory`)
    directory = entry
  }
  directory.entries.set(parts[parts.length - 1]!, { bytes: new Uint8Array(bytes) })
}

function readMemoryFile(root: MemoryDirectory, path: string): Uint8Array | undefined {
  const parts = path.split('/')
  let directory = root
  for (const part of parts.slice(0, -1)) {
    const entry = directory.entries.get(part)
    if (!entry || !('entries' in entry)) return undefined
    directory = entry
  }
  const entry = directory.entries.get(parts[parts.length - 1]!)
  return entry && 'bytes' in entry ? entry.bytes : undefined
}

function line(audioPath: string | null): ScriptLine {
  return {
    id: 'line-1',
    speaker: 'narrator',
    display_text: '目录保存测试',
    tts_text: '目录保存测试',
    index: 0,
    audio_path: audioPath,
    overlay: null,
    stage_id: '',
  }
}

function stubAudioFetch(audioBytes: Uint8Array): void {
  vi.stubGlobal(
    'fetch',
    vi.fn().mockResolvedValue(
      new Response(audioBytes, {
        headers: { 'Content-Type': 'audio/wav' },
      }),
    ),
  )
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

describe('A2D project directory', () => {
  it('writes the ZIP v2 manifest and referenced resources into the selected folder', async () => {
    const store = useScriptStore()
    store.projectName = '目录往返'
    store.lines = [line('/audio/a2d_line-1.wav')]
    const audioBytes = new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69])
    stubAudioFetch(audioBytes)
    const directory = createMemoryDirectory()

    await saveA2DProjectToDirectory(directory.handle)

    const manifestBytes = readMemoryFile(directory.node, 'project.json')
    expect(manifestBytes).toBeDefined()
    const manifest = JSON.parse(new TextDecoder().decode(manifestBytes))
    expect(manifest.format).toBe('a2d-studio-project')
    expect(manifest.script.project_name).toBe('目录往返')
    expect(Array.from(readMemoryFile(directory.node, 'assets/audio/line-0001.wav')!)).toEqual(
      Array.from(audioBytes),
    )
  })

  it('opens the manifest and referenced assets from a directory through the ZIP v2 importer', async () => {
    const store = useScriptStore()
    store.projectName = '目录项目'
    store.lines = [line('/audio/a2d_line-1.wav')]
    const audioBytes = new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69])
    stubAudioFetch(audioBytes)
    const archive = await packA2DProject(buildExportEnvelope(), '目录项目')
    const directory = createMemoryDirectory()
    for (const [path, bytes] of Object.entries(unzipSync(archive)))
      writeMemoryFile(directory.node, path, bytes)
    const previousCreateObjectURL = Object.getOwnPropertyDescriptor(URL, 'createObjectURL')
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:directory-import'),
    })

    try {
      store.projectName = '待替换项目'
      const result = await openA2DProjectFromDirectory(directory.handle)

      expect(result.ok, result.error).toBe(true)
      expect(store.projectName).toBe('目录项目')
      expect(store.lines[0].audio_path).toBe('blob:directory-import')
    } finally {
      if (previousCreateObjectURL)
        Object.defineProperty(URL, 'createObjectURL', previousCreateObjectURL)
      else Reflect.deleteProperty(URL, 'createObjectURL')
    }
  })

  it('rejects a directory with a missing declared asset without changing the current project', async () => {
    const store = useScriptStore()
    store.lines = [line('/audio/a2d_line-1.wav')]
    stubAudioFetch(new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69]))
    const archive = await packA2DProject(buildExportEnvelope(), '不完整目录')
    const files = unzipSync(archive)
    const directory = createMemoryDirectory()
    writeMemoryFile(directory.node, 'project.json', files['project.json'])
    store.projectName = '当前项目'

    const result = await openA2DProjectFromDirectory(directory.handle)

    expect(result.ok).toBe(false)
    expect(result.error).toContain('assets/audio/line-0001.wav')
    expect(store.projectName).toBe('当前项目')
  })

  it('does not overwrite an existing resource in a folder without an A2D manifest', async () => {
    const store = useScriptStore()
    store.lines = [line('/audio/a2d_line-1.wav')]
    stubAudioFetch(new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69]))
    const directory = createMemoryDirectory()
    const existingBytes = new Uint8Array([1, 2, 3])
    writeMemoryFile(directory.node, 'assets/audio/line-0001.wav', existingBytes)

    await expect(saveA2DProjectToDirectory(directory.handle)).rejects.toThrow('已拒绝覆盖')

    expect(Array.from(readMemoryFile(directory.node, 'assets/audio/line-0001.wav')!)).toEqual(
      Array.from(existingBytes),
    )
    expect(readMemoryFile(directory.node, 'project.json')).toBeUndefined()
  })

  it('reuses stale A2D asset paths when a resource is removed and later regenerated', async () => {
    const store = useScriptStore()
    const directory = createMemoryDirectory()
    const firstAudio = new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69])
    stubAudioFetch(firstAudio)
    store.lines = [line('/audio/a2d_line-1.wav')]
    await saveA2DProjectToDirectory(directory.handle)

    store.lines = [line(null)]
    await saveA2DProjectToDirectory(directory.handle)
    const replacementAudio = new Uint8Array([65, 66, 67, 68, 69, 70, 71, 72])
    stubAudioFetch(replacementAudio)
    store.lines = [line('/audio/a2d_line-1.wav')]

    await expect(saveA2DProjectToDirectory(directory.handle)).resolves.toBeUndefined()
    expect(Array.from(readMemoryFile(directory.node, 'assets/audio/line-0001.wav')!)).toEqual(
      Array.from(replacementAudio),
    )
  })
})
