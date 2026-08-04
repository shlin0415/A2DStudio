import { describe, it, expect } from 'vitest'
import { resolveVisual } from '@/composables/overlay-resolve'
import type { ScriptLine } from '@/stores/modules/script'

function makeLine(overrides: Partial<ScriptLine> = {}): ScriptLine {
  return {
    id: 'l1', speaker: 'ema', display_text: 't', tts_text: 't', index: 0,
    audio_path: null, overlay: null, stage_id: '', ...overrides,
  }
}

describe('resolveVisual', () => {
  it('returns null for null line', () => {
    expect(resolveVisual(null)).toBeNull()
  })

  it('applies line > stage > global background priority chain', () => {
    // Line background wins.
    const a = resolveVisual(makeLine({ overlay: { background: 'line.webp' } as any }))
    expect(a?.background).toBe('line.webp')

    // Stage background when line has none.
    const b = resolveVisual(makeLine({ stage_id: 's1' }), { s1: 'stage.webp' })
    expect(b?.background).toBe('stage.webp')

    // Global fallback when neither line nor stage.
    const c = resolveVisual(makeLine(), {}, 'global.webp')
    expect(c?.background).toBe('global.webp')

    // null when no background anywhere.
    const d = resolveVisual(makeLine())
    expect(d?.background).toBeNull()
  })

  it('extracts text overlays', () => {
    const v = resolveVisual(makeLine({
      overlay: { text_overlays: [{ id: 't1', text: '标题', x: 50, y: 10, width: 0, font_size: 24, color: '#fff', opacity: 1, z: 0 }] } as any,
    }))
    expect(v?.textOverlays).toHaveLength(1)
    expect(v?.textOverlays[0]).toMatchObject({ text: '标题', x: 50, y: 10 })
  })

  it('extracts image overlays', () => {
    const v = resolveVisual(makeLine({
      overlay: { image_overlays: [{ id: 'i1', path: 'x.png', x: 80, y: 80, w: 100, h: 100, opacity: 0.8, z: 1 }] } as any,
    }))
    expect(v?.imageOverlays).toHaveLength(1)
    expect(v?.imageOverlays[0]).toMatchObject({ path: 'x.png', opacity: 0.8 })
  })

  it('extracts sprite positions', () => {
    const v = resolveVisual(makeLine({
      overlay: { sprite_positions: { ema: { x: 30, y: 60, scale: 1.2 } } } as any,
    }))
    expect(v?.sprites).toEqual({ ema: { x: 30, y: 60, scale: 1.2 } })
  })

  it('extracts BGM fields', () => {
    const v = resolveVisual(makeLine({
      overlay: { bgm: 'track.mp3', bgm_volume: 0.5, bgm_loop: false } as any,
    }))
    expect(v?.bgm).toBe('track.mp3')
    expect(v?.bgmVolume).toBe(0.5)
    expect(v?.bgmLoop).toBe(false)
  })

  it('defaults BGM fields when overlay is null', () => {
    const v = resolveVisual(makeLine())
    expect(v?.bgm).toBe('')
    expect(v?.bgmVolume).toBe(1)
    expect(v?.bgmLoop).toBe(true)
  })
})
