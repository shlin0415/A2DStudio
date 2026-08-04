import type { LineOverlay } from '@/stores/modules/script'

/**
 * Pre-resolved per-line visual state for replay rendering.
 *
 * The replay engine runs the line>stage>global priority chain at start() time
 * and flattens the result into this struct, so StageOverlay stays a pure
 * presentational component with no cross-line data dependencies.
 */
export interface ResolvedLineVisual {
  /** Resolved background image path (priority chain already applied). */
  background: string | null
  /** Per-speaker sprite offset/scale. */
  sprites: Record<string, { x: number; y: number; scale: number }>
  /** Screen text overlays (static — non-editable in P1). */
  textOverlays: ExtractedTextOverlay[]
  /** Image overlay layers. */
  imageOverlays: ExtractedImageOverlay[]
  /** BGM track path (empty string = no BGM). */
  bgm: string
  bgmVolume: number
  bgmLoop: boolean
  /** Raw overlay (for P4 editor to mutate). */
  raw: LineOverlay | null
}

export interface ExtractedTextOverlay {
  id: string
  text: string
  x: number
  y: number
  width: number
  fontSize: number
  color: string
  opacity: number
  z: number
}

export interface ExtractedImageOverlay {
  id: string
  path: string
  x: number
  y: number
  w: number
  h: number
  opacity: number
  z: number
}

/**
 * Replay engine state machine states.
 * idle → loading → playing ↔ paused → seeking → idle
 */
export type ReplayState = 'idle' | 'loading' | 'playing' | 'paused' | 'seeking'
