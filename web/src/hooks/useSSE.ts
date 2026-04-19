import { useEffect, useRef, useCallback, useState } from 'react'
import { createSSE, type Message } from '../lib/api'

const MAX_RECONNECT_DELAY = 30000
const BASE_RECONNECT_DELAY = 1000
const MAX_RECONNECT_ATTEMPTS = 15
const CONNECTION_TIMEOUT = 10000 // 10秒连接超时

export type SSEStatus = 'connecting' | 'connected' | 'reconnecting' | 'error'

export function useSSE(
  onMessage: (msg: Message, id: string) => void,
  enabled: boolean = true
) {
  const esRef = useRef<EventSource | null>(null)
  const [status, setStatus] = useState<SSEStatus>('connecting')
  const [reconnectIn, setReconnectIn] = useState(0)
  const attemptsRef = useRef(0)
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  const connectionTimerRef = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)
  // 用 ref 追踪当前状态，避免闭包问题
  const statusRef = useRef<SSEStatus>('connecting')
  statusRef.current = status

  const clearTimers = useCallback(() => {
    if (connectionTimerRef.current) {
      clearTimeout(connectionTimerRef.current)
      connectionTimerRef.current = undefined
    }
    if (reconnectTimer.current) {
      clearInterval(reconnectTimer.current)
      reconnectTimer.current = undefined
    }
  }, [])

  const connect = useCallback(() => {
    if (esRef.current) esRef.current.close()
    clearTimers()

    setStatus('connecting')
    let hasReceivedMessage = false

    const es = createSSE(
      parseInt(localStorage.getItem('lastEventId') || '0'),
      (msg, id) => {
        // 收到任何消息（包括心跳），说明连接正常
        if (!hasReceivedMessage) {
          hasReceivedMessage = true
          attemptsRef.current = 0
        }
        setStatus('connected')
        localStorage.setItem('lastEventId', id)
        onMessage(msg, id)
      },
      () => {
        // EventSource 错误 - 使用 ref 判断当前状态
        if (!hasReceivedMessage && statusRef.current === 'connecting') {
          setStatus('error')
          return
        }
        // 已连接过的连接断开，进入重连流程
        if (hasReceivedMessage || statusRef.current === 'connected') {
          setStatus('reconnecting')
          scheduleReconnect()
        }
      }
    )

    es.onopen = () => {
      // 连接打开后，设置超时检测
      connectionTimerRef.current = setTimeout(() => {
        if (!hasReceivedMessage && es.readyState === EventSource.OPEN) {
          // 10秒内没收到任何消息（包括心跳），判定为连接失败
          es.close()
          setStatus('error')
        }
      }, CONNECTION_TIMEOUT)
    }

    esRef.current = es
  }, [onMessage, clearTimers])

  const scheduleReconnect = useCallback(() => {
    if (attemptsRef.current >= MAX_RECONNECT_ATTEMPTS) {
      setStatus('error')
      return
    }

    attemptsRef.current++
    const delay = Math.min(BASE_RECONNECT_DELAY * Math.pow(2, attemptsRef.current - 1), MAX_RECONNECT_DELAY)
    const jitter = Math.random() * 300
    const totalDelay = delay + jitter

    // 使用局部变量追踪倒数，避免依赖 prev 状态闭包触发副作用
    let countdown = Math.ceil(totalDelay / 1000)
    setReconnectIn(countdown)

    reconnectTimer.current = setInterval(() => {
      countdown -= 1
      setReconnectIn(countdown) // 只做纯状态更新

      if (countdown <= 0) {
        // 在外层执行副作用
        if (reconnectTimer.current) clearInterval(reconnectTimer.current)
        connect()
      }
    }, 1000)
  }, [connect])

  useEffect(() => {
    if (enabled) connect()
    return () => {
      clearTimers()
      esRef.current?.close()
    }
  }, [enabled, connect, clearTimers])

  return { status, reconnectIn }
}
