import { onMounted, onUnmounted } from 'vue'
import { useScriptStore } from '@/stores/modules/script'
import type { ScriptLine, ErrorInfo, Phase } from '@/stores/modules/script'

export function useA2DWebSocket() {
  const store = useScriptStore()
  let ws: WebSocket | null = null
  const WS_URL = `ws://${window.location.hostname}:8765/ws`

  function connect() {
    ws = new WebSocket(WS_URL)

    ws.onopen = () => {
      console.log('[A2D] WebSocket connected')
    }

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data)
      handleMessage(msg)
    }

    ws.onclose = () => {
      console.log('[A2D] WebSocket closed')
    }

    ws.onerror = (e) => {
      console.error('[A2D] WebSocket error', e)
    }
  }

  function handleMessage(msg: { type: string; payload: any }) {
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
        const line = msg.payload as ScriptLine
        store.addLine(line)
        break
      }

      case 'tts_ready': {
        store.setPhase('paused')
        const audioPath = msg.payload?.audio_path
        if (audioPath) {
          const audio = new Audio(audioPath)
          audio.play().catch(e => console.error('[A2D] audio play failed', e))
        }
        break
      }

      case 'error': {
        const err = msg.payload as ErrorInfo
        store.setError(err)
        break
      }

      default:
        console.log('[A2D] unknown message type:', msg.type)
    }
  }

  function sendStart(topic?: string) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({
      type: 'a2d.start',
      payload: { topic },
    }))
  }

  function sendContinue(edits?: { id: string; text: string }[]) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({
      type: 'a2d.continue',
      payload: {
        generation_id: store.generationId,
        edits: edits || [],
      },
    }))
  }

  function sendRetry() {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({
      type: 'a2d.retry',
      payload: { generation_id: store.generationId },
    }))
  }

  function sendRegenerateTTS(id: string, text: string) {
    if (!ws || ws.readyState !== WebSocket.OPEN) return
    ws.send(JSON.stringify({
      type: 'a2d.regenerate_tts',
      payload: { id, text },
    }))
  }

  function disconnect() {
    if (ws) {
      ws.close()
      ws = null
    }
  }

  onMounted(() => {
    connect()
  })

  onUnmounted(() => {
    disconnect()
  })

  return {
    connect, disconnect,
    sendStart, sendContinue, sendRetry, sendRegenerateTTS,
  }
}
