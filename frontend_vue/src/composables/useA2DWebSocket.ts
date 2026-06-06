import { onMounted, onUnmounted } from 'vue'
import { useScriptStore } from '@/stores/modules/script'
import type { ScriptLine, ErrorInfo, Phase } from '@/stores/modules/script'

// ── Singleton: shared WS across all components ─────────
let ws: WebSocket | null = null
let connected = false

export function useA2DWebSocket() {
  const store = useScriptStore()
  const WS_URL = `ws://${window.location.hostname}:8765/ws`

  function connect() {
    if (ws && ws.readyState === WebSocket.OPEN) return
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
        case 'status': {
          const phase = (msg.payload?.phase || 'idle') as Phase
          store.setPhase(phase)
          break
        }
        case 'script_line': {
          store.addLine(msg.payload as ScriptLine)
          break
        }
        case 'tts_ready': {
          store.setPhase('paused')
          const audioPath = msg.payload?.audio_path
          if (audioPath) {
            new Audio(audioPath).play().catch(e =>
              console.error('[A2D] audio play failed', e)
            )
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

  function sendStart(topic?: string) {
    send({ type: 'a2d.start', payload: { topic } })
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
    sendStart, sendContinue, sendRetry, sendRegenerateTTS,
  }
}
