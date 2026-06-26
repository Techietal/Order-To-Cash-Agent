import { useEffect, useRef } from 'react'
import { usePipelineStore } from '../store'

const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'

const WS_URL =
  import.meta.env.VITE_WS_URL ||
  API_URL.replace(/^http/, 'ws').replace(/\/$/, '') + '/ws/pipeline'

export function usePipelineWS() {
  const { addEvent, setConnected } = usePipelineStore()
  const wsRef = useRef(null)
  const retryRef = useRef(null)

  useEffect(() => {
    function connect() {
      console.log('WebSocket URL:', WS_URL)

      const ws = new WebSocket(WS_URL)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)

        if (retryRef.current) {
          clearTimeout(retryRef.current)
          retryRef.current = null
        }

        const ping = setInterval(() => {
          if (ws.readyState === WebSocket.OPEN) {
            ws.send('ping')
          }
        }, 30000)

        ws._ping = ping
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)

          if (msg.type !== 'pong') {
            addEvent(msg)
          }
        } catch (_) {
          // ignore invalid websocket messages
        }
      }

      ws.onclose = () => {
        setConnected(false)

        if (ws._ping) {
          clearInterval(ws._ping)
        }

        retryRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => {
        ws.close()
      }
    }

    connect()

    return () => {
      if (wsRef.current?._ping) {
        clearInterval(wsRef.current._ping)
      }

      wsRef.current?.close()

      if (retryRef.current) {
        clearTimeout(retryRef.current)
      }
    }
  }, [addEvent, setConnected])
}