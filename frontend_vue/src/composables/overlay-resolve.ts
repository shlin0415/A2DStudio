import type { ScriptLine } from '@/stores/modules/script'
import type { ResolvedLineVisual, ExtractedTextOverlay, ExtractedImageOverlay } from '@/composables/types'

/**
 * Resolve a ScriptLine's overlay into a flat ResolvedLineVisual.
 *
 * Applies the line → stage → global background priority chain so the renderer
 * (StageOverlay) stays pure. Pure function — unit-testable without mounting.
 *
 * NOTE: stageMap/globalBackground come from the export envelope's stages/meta.
 * For live WS lines without stage context, falls back to globalDefault ('').
 */
export function resolveVisual(line: ScriptLine | null, stageMap: Record<string, string> = {}, globalDefault: string = ''): ResolvedLineVisual | null {
  if (!line) return null
  const ov = line.overlay

  // Priority chain: line.overlay.background → stage.default_background → global.
  const stageBg = line.stage_id ? (stageMap[line.stage_id] ?? '') : ''
  const background = ov?.background ?? ((stageBg || globalDefault) || null)

  const sprites = ov?.sprite_positions ?? {}

  const textOverlays: ExtractedTextOverlay[] = (ov?.text_overlays ?? []).map(t => ({
    id: t.id, text: t.text, x: t.x, y: t.y, width: t.width,
    fontSize: t.font_size, color: t.color, opacity: t.opacity, z: t.z,
  }))

  const imageOverlays: ExtractedImageOverlay[] = (ov?.image_overlays ?? []).map(img => ({
    id: img.id, path: img.path, x: img.x, y: img.y, w: img.w, h: img.h,
    opacity: img.opacity, z: img.z,
  }))

  return {
    background,
    sprites,
    textOverlays,
    imageOverlays,
    bgm: ov?.bgm ?? '',
    bgmVolume: ov?.bgm_volume ?? 1,
    bgmLoop: ov?.bgm_loop ?? true,
    raw: ov,
  }
}
