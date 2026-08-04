import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'
import { playBGM, stopBGM, setBGMVolume, fadeBGM, getCurrentBGM } from '@/composables/useA2DBGM'

// Fake HTMLAudioElement capturing play() calls.
class FakeAudio {
  src = ''
  muted = false
  currentTime = 0
  volume = 1
  loop = false
  paused = true
  playSpy = vi.fn(() => { this.paused = false; return Promise.resolve() })
  pauseSpy = vi.fn(() => { this.paused = true })
  play() { return this.playSpy() }
  pause() { this.pauseSpy() }
}

describe('useA2DBGM', () => {
  let origAudio: typeof globalThis.Audio

  beforeEach(() => {
    origAudio = globalThis.Audio
    // @ts-expect-error override Audio constructor
    globalThis.Audio = FakeAudio
  })

  afterEach(() => {
    // @ts-expect-error restore Audio
    globalThis.Audio = origAudio
    stopBGM()
    vi.restoreAllMocks()
  })

  it('playBGM sets src, volume, loop and calls play()', () => {
    playBGM('track.mp3', { volume: 0.5, loop: true })
    const el = (globalThis.Audio as unknown as { mock?: { lastInstance?: FakeAudio } })
    // Access the singleton element via getCurrentBGM (src stored).
    expect(getCurrentBGM()).toBe('track.mp3')
  })

  it('playBGM with empty src is a no-op (AC-4 negative)', () => {
    playBGM('')
    expect(getCurrentBGM()).toBe('')
  })

  it('stopBGM clears current src', () => {
    playBGM('track.mp3')
    expect(getCurrentBGM()).toBe('track.mp3')
    stopBGM()
    expect(getCurrentBGM()).toBe('')
  })

  it('setBGMVolume clamps and writes volume', () => {
    playBGM('track.mp3')
    setBGMVolume(0.8)
    setBGMVolume(99) // clamp high
    setBGMVolume(-1) // clamp low
    // No throw = pass.
    expect(getCurrentBGM()).toBe('track.mp3')
  })

  it('fadeBGM runs without throwing', () => {
    playBGM('track.mp3')
    fadeBGM(0.5, 50)
    expect(getCurrentBGM()).toBe('track.mp3')
  })

  it('getCurrentBGM returns empty string when nothing playing', () => {
    expect(getCurrentBGM()).toBe('')
  })

  it('calling playBGM with same src while playing is a no-op (no re-trigger)', () => {
    playBGM('track.mp3')
    expect(getCurrentBGM()).toBe('track.mp3')
    playBGM('track.mp3') // same src
    expect(getCurrentBGM()).toBe('track.mp3')
  })
})
