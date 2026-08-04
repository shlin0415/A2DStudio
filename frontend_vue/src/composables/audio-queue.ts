/**
 * Shared audio queue state — single source of truth for both live WS playback
 * and replay engine. useA2DWebSocket drives playNextInQueue; useA2DReplay
 * enqueues items and owns the queue during playback (replayActive).
 */
import { ref } from 'vue'

export interface AudioQueueItem {
  url: string
  lineId: string
}

/** Active playback queue (live WS or replay). */
export const audioQueue = ref<AudioQueueItem[]>([])

/** Whether any audio is currently playing. */
export const isAudioPlaying = ref(false)

/** Live TTS deferred while replay is active (DEC-2: deferred queue + toast). */
export const pendingLiveQueue = ref<AudioQueueItem[]>([])

/** When replay ends, drain pending live items into the active queue. */
export function drainPendingLiveQueue(): AudioQueueItem[] {
  const items = pendingLiveQueue.value.splice(0)
  audioQueue.value.push(...items)
  return items
}
