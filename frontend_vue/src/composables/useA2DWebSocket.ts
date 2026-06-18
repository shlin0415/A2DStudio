import { onMounted, onUnmounted } from 'vue'
import { useScriptStore } from '@/stores/modules/script'
import { useGameStore } from '@/stores/modules/game'
import type { ScriptLine, ErrorInfo, Phase } from '@/stores/modules/script'
import type { GameRole } from '@/stores/modules/game/state'

// ── Singleton: shared WS across all components ─────────
let ws: WebSocket | null = null
let connected = false

// speaker-to-roleId mapping built from a2d.characters payload
const speakerToRoleId: Record<string, number> = {}

// ── Audio queue: sequential playback to prevent overlap ────
const audioQueue: string[] = []
let isAudioPlaying = false

function playNextInQueue() {
  if (audioQueue.length === 0) {
    isAudioPlaying = false
    return
  }
  isAudioPlaying = true
  const url = audioQueue.shift()!
  const audio = new Audio(url)
  audio.onended = () => playNextInQueue()
  audio.onerror = () => playNextInQueue()
  audio.play().catch(() => playNextInQueue())
}

export function useA2DWebSocket() {
  const store = useScriptStore()
  const WS_URL = `ws://${window.location.hostname}:8765/ws`

  function connect() {
    if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return
    ws = new WebSocket(WS_URL)

    ws.onopen = () => {
      connected = true
      console.log('[A2D] WebSocket connected')
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      switch (msg.type) {
        case 'connection_established':
          store.generationId = msg.payload?.client_id || null
          break
        case 'a2d.characters': {
          const gameStore = useGameStore()
          const chars = msg.payload?.characters as Record<string, unknown>[]
          if (chars && chars.length > 0) {
            gameStore.presentRoleIds = []
            for (const c of chars) {
              const roleId = c.roleId as number
              const scriptRoleKey = (c.script_role_key as string) || ''
              // Build speaker-to-roleId mapping for emotion propagation
              if (scriptRoleKey) {
                speakerToRoleId[scriptRoleKey] = roleId
              }
              // Only create if not already present (idempotent on restart)
              if (!gameStore.gameRoles[roleId]) {
                gameStore.gameRoles[roleId] = {
                  roleId,
                  roleName: (c.roleName as string) || '',
                  roleSubTitle: (c.roleSubTitle as string) || '',
                  thinkMessage: (c.thinkMessage as string) || '正在思考中...',
                  emotion: '正常',
                  originalEmotion: '正常',
                  scale: (c.scale as number) || 1.0,
                  offsetX: (c.offsetX as number) || 0,
                  offsetY: (c.offsetY as number) || 0,
                  bubbleTop: (c.bubbleTop as number) || 5,
                  bubbleLeft: (c.bubbleLeft as number) || 20,
                  show: true,
                  clothes: {},
                  clothesName: 'default',
                  bodyPart: {},
                  character_folder: (c.character_folder as string) || '',
                } as GameRole
              }
              gameStore.presentRoleIds.push(roleId)
            }
            console.log('[A2D] characters loaded:', gameStore.presentRoleIds,
              'speakerToRoleId:', speakerToRoleId)
          }
          break
        }
        case 'status': {
          const phase = (msg.payload?.phase || 'idle') as Phase
          store.setPhase(phase)
          break
        }
        case 'script_line': {
          store.addLine(msg.payload as ScriptLine)
          // Propagate emotion to character avatar rendering
          const payload = msg.payload as Record<string, unknown>
          const speaker = payload.speaker as string
          const emotion = (payload.emotion as string) || ''
          if (speaker && emotion) {
            const roleId = speakerToRoleId[speaker]
            if (roleId) {
              const gameStore = useGameStore()
              if (gameStore.gameRoles[roleId]) {
                gameStore.gameRoles[roleId].emotion = emotion
                gameStore.gameRoles[roleId].originalEmotion = emotion
              }
            }
          }
          break
        }
        case 'tts_ready': {
          // Do NOT set paused here — status(paused) from backend signals batch end.
          // Multi-line batches send tts_ready per line; paused only after the last one.
          const audioPath = msg.payload?.audio_path
          if (audioPath) {
            // audio_path is a URL path like /audio/a2d_xxx.wav
            const url = audioPath.startsWith('/')
              ? `http://${window.location.hostname}:8765${audioPath}`
              : audioPath
            // Queue for sequential playback — prevents overlap when batch_size > 1
            // or when LLM returns multiple lines despite batch_size=1
            audioQueue.push(url)
            if (!isAudioPlaying) {
              playNextInQueue()
            }
          }
          break
        }
        case 'error': {
          store.setError(msg.payload as ErrorInfo)
          break
        }
        default:
          break
      }
    }

    ws.onclose = () => {
      connected = false
      console.log('[A2D] WebSocket closed')
    }

    ws.onerror = (e) => {
      console.error('[A2D] WebSocket error', e)
    }
  }

  function send(msg: Record<string, unknown>) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      console.warn('[A2D] WS not open, dropping message:', msg.type)
      return
    }
    ws.send(JSON.stringify(msg))
  }

  function sendStart(opts?: { topic?: string; batchSize?: number }) {
    send({ type: 'a2d.start', payload: { topic: opts?.topic, batch_size: opts?.batchSize ?? 1 } })
  }

  function sendSetBatchSize(batchSize: number) {
    send({ type: 'a2d.set_batch_size', payload: { batch_size: batchSize } })
  }

  function sendContinue(edits?: { id: string; text: string }[]) {
    send({
      type: 'a2d.continue',
      payload: { generation_id: store.generationId, edits: edits || [] },
    })
  }

  function sendRetry() {
    send({ type: 'a2d.retry', payload: { generation_id: store.generationId } })
  }

  function sendRegenerateTTS(id: string, text: string) {
    send({ type: 'a2d.regenerate_tts', payload: { id, text } })
  }

  /** Log user interaction (click, edit) to backend log file via WS. */
  function logUserAction(action: string, target: string, detail?: string) {
    send({
      type: 'a2d.user_action',
      payload: { action, target, detail: detail || '', timestamp: Date.now() },
    })
    // Also log to browser console for immediate visibility
    console.info(`[A2D-User] ${action} | ${target}${detail ? ' | ' + detail : ''}`)
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
      connected = false
    }
  }

  // Auto-connect on first component mount, never on subsequent ones
  onMounted(() => {
    if (!connected) connect()
  })

  // Only disconnect on unmount if this is the last component
  // (we never auto-disconnect — connection persists for session lifetime)

  return {
    connect, disconnect,
    sendStart, sendContinue, sendRetry, sendRegenerateTTS, sendSetBatchSize,
    logUserAction,
  }
}
