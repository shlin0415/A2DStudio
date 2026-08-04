/**
 * BGM playback singleton — wraps one HTMLAudioElement for long-looping background music.
 * Replaces the 60Hz sine placeholder in useA2DWebSocket.ts (which was a WASAPI keepalive, not BGM).
 */
import { ref } from 'vue'

let bgmEl: HTMLAudioElement | null = null
const currentSrc = ref('')

function getElement(): HTMLAudioElement {
  if (!bgmEl) {
    bgmEl = new Audio()
    bgmEl.loop = true
  }
  return bgmEl
}

/** Play a BGM track. No-op for empty/invalid src (AC-4 negative: invalid path must not break replay). */
export function playBGM(src: string, opts: { volume?: number; loop?: boolean } = {}): void {
  if (!src) return
  const el = getElement()
  const srcChanged = el.src !== src && currentSrc.value !== src
  if (!srcChanged && !el.paused) return // already playing this track
  el.src = src
  el.loop = opts.loop ?? true
  if (opts.volume != null) el.volume = Math.max(0, Math.min(1, opts.volume))
  currentSrc.value = src
  el.play().catch(() => { /* autoplay blocked */ })
}

/** Stop BGM playback. */
export function stopBGM(): void {
  if (!bgmEl) return
  bgmEl.pause()
  bgmEl.currentTime = 0
  currentSrc.value = ''
}

/** Fade volume to target over ms. */
export function fadeBGM(targetVolume: number, ms: number): void {
  if (!bgmEl) return
  const start = bgmEl.volume
  const steps = 20
  const interval = ms / steps
  let i = 0
  const id = setInterval(() => {
    i++
    if (bgmEl) bgmEl.volume = start + (targetVolume - start) * (i / steps)
    if (i >= steps) clearInterval(id)
  }, interval)
}

/** Set volume immediately. */
export function setBGMVolume(v: number): void {
  if (bgmEl) bgmEl.volume = Math.max(0, Math.min(1, v))
}

/** Current BGM track path (empty = stopped). */
export function getCurrentBGM(): string {
  return currentSrc.value
}
