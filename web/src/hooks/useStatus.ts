import { useState, useEffect, useCallback } from 'react'
import type { ServerStatus } from '@/lib/types'

const BASE = 'http://localhost:8765'

async function getStatus(): Promise<ServerStatus> {
  const res = await fetch(`${BASE}/api/status`)
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
  return res.json()
}

export function useStatus() {
  const [status, setStatus] = useState<ServerStatus | null>(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(async () => {
    try {
      const data = await getStatus()
      setStatus(data)
    } catch (e) {
      console.error('Status fetch error:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    refresh()
    const interval = setInterval(refresh, 10000)
    return () => clearInterval(interval)
  }, [refresh])

  return { status, loading, refresh }
}
