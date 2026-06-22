import { useEffect, useRef } from 'react'
import { usePipelineStore } from '../store'

export function usePipelineWS() {
  const { addEvent, setConnected } = usePipelineStore()
  const wsRef = useRef(null)
  const retryRef = useRef(null)

  useEffect(() => {
    function connect() {
      const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:'
      const ws = new WebSocket(`${protocol}//${window.location.host}/ws/pipeline`)
      wsRef.current = ws

      ws.onopen = () => {
        setConnected(true)
        retryRef.current && clearTimeout(retryRef.current)
        // Ping every 30s
        const ping = setInterval(() => ws.readyState === 1 && ws.send('ping'), 30000)
        ws._ping = ping
      }

      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data)
          if (msg.type !== 'pong') addEvent(msg)
        } catch (_) {}
      }

      ws.onclose = () => {
        setConnected(false)
        retryRef.current = setTimeout(connect, 3000)
      }

      ws.onerror = () => ws.close()
    }

    connect()
    return () => {
      wsRef.current?.close()
      retryRef.current && clearTimeout(retryRef.current)
    }
  }, [])
}
