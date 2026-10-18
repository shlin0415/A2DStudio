import { beforeEach, describe, expect, it } from 'vitest'
import { createPinia, setActivePinia } from 'pinia'
import { useScriptStore } from '../script'

describe('manual script editing', () => {
  beforeEach(() => setActivePinia(createPinia()))

  it('creates a selected manual line in the script editor', () => {
    const store = useScriptStore()

    const line = store.createManualLine('ema')

    expect(line.speaker).toBe('ema')
    expect(line.index).toBe(0)
    expect(line.audio_path).toBeNull()
    expect(store.selectedLineId).toBe(line.id)
    expect(store.activeTab).toBe('script')
  })

  it('invalidates audio when speech text or speaker changes', () => {
    const store = useScriptStore()
    const line = store.createManualLine('ema')
    store.setAudioPath(line.id, '/audio/a2d_line.wav')

    store.updateLine(line.id, { display_text: '改过的台词', tts_text: '改过的台词' })

    expect(store.lines[0].audio_path).toBeNull()
    expect(store.lines[0].display_text).toBe('改过的台词')
  })

  it('removes lines and keeps indexes and selection valid', () => {
    const store = useScriptStore()
    const first = store.createManualLine('ema')
    const second = store.createManualLine('hiro')
    store.selectLine(first.id)

    store.removeLine(first.id)

    expect(store.lines).toHaveLength(1)
    expect(store.lines[0].id).toBe(second.id)
    expect(store.lines[0].index).toBe(0)
    expect(store.selectedLineId).toBe(second.id)
  })

  it('reorders lines without changing their audio', () => {
    const store = useScriptStore()
    const first = store.createManualLine('ema')
    const second = store.createManualLine('hiro')
    store.setAudioPath(first.id, '/audio/a2d_first.wav')

    store.moveLine(first.id, 1)

    expect(store.lines.map((line) => line.id)).toEqual([second.id, first.id])
    expect(store.lines[1].index).toBe(1)
    expect(store.lines[1].audio_path).toBe('/audio/a2d_first.wav')
  })
})
