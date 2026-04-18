import { Wifi, WifiOff, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SSEStatus } from '@/hooks/useSSE'

interface StatusBarProps {
  sseStatus: SSEStatus
  reconnectIn?: number
}

export function StatusBar({ sseStatus, reconnectIn }: StatusBarProps) {
  return (
    <div className="flex items-center gap-2 px-3 py-2 text-xs border-t bg-muted/30">
      {sseStatus === 'connected' ? (
        <>
          <Wifi className="h-3 w-3 text-status-online" />
          <span className="text-muted-foreground">SSE已连接</span>
        </>
      ) : sseStatus === 'connecting' ? (
        <>
          <Loader2 className="h-3 w-3 text-status-warning animate-spin" />
          <span className="text-muted-foreground">连接中...</span>
        </>
      ) : sseStatus === 'reconnecting' ? (
        <>
          <Loader2 className="h-3 w-3 text-status-warning animate-spin" />
          <span className="text-muted-foreground">重连中 ({reconnectIn}s)</span>
        </>
      ) : (
        <>
          <WifiOff className="h-3 w-3 text-status-error" />
          <span className="text-destructive">连接失败</span>
        </>
      )}
    </div>
  )
}
