import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { strFromU8, unzipSync, zipSync } from 'fflate'
import { useScriptStore, type ScriptLine } from '@/stores/modules/script'
import { buildExportEnvelope } from '@/composables/useA2DSaveLoad'
import { exportA2DProject, packA2DProject, unpackA2DProject } from '@/composables/useA2DProject'

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

describe('A2D project archive', () => {
  it('packages script and audio under relative paths without local service settings', async () => {
    const envelope = buildExportEnvelope()
    envelope.script.lines = [makeLine('line-1', '/audio/a2d_line-1.wav')]
    envelope.script.projectName = '双人短剧'
    const audioBytes = new Uint8Array([82, 73, 70, 70, 87, 65, 86, 69])
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(audioBytes)))

    const archive = await packA2DProject(envelope, '双人短剧')
    const files = unzipSync(archive)
    const manifest = JSON.parse(strFromU8(files['project.json']))

    expect(manifest.title).toBe('双人短剧')
    expect(manifest.envelope.script.lines[0].audio_path).toBe('assets/audio/line-0001.wav')
    expect(Array.from(files['assets/audio/line-0001.wav'])).toEqual(Array.from(audioBytes))
    expect(strFromU8(files['project.json'])).not.toContain('CHAT_API_KEY')
  })

  it('opens a project archive and restores its bundled audio as a replayable URL', async () => {
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
    Object.defineProperty(URL, 'createObjectURL', {
      configurable: true,
      value: vi.fn(() => 'blob:project-audio'),
    })
    Object.defineProperty(URL, 'revokeObjectURL', {
      configurable: true,
      value: vi.fn(),
    })

    const result = await unpackA2DProject(new File([archive], 'short.a2d.zip'))

    expect(result.ok).toBe(true)
    expect(useScriptStore().projectName).toBe('短剧')
    expect(useScriptStore().lines[0].audio_path).toBe('blob:project-audio')
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
