import { Wifi, WifiOff, Loader2 } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { SSEStatus } from '@/hooks/useSSE'

interface ServiceStatusProps {
  serverOnline: boolean
  pollRunning: boolean
  sseStatus: SSEStatus
  reconnectIn?: number
}

export function ServiceStatus({ serverOnline, pollRunning, sseStatus, reconnectIn }: ServiceStatusProps) {
  return (
    <div className="flex items-center gap-3 text-xs">
      {/* Server status */}
      <div className="flex items-center gap-1">
        <span className={cn(
          "w-2 h-2 rounded-full",
          serverOnline ? "bg-status-online" : "bg-status-error"
        )} />
        <span className="text-muted-foreground">服务器</span>
      </div>

      {/* Poll status */}
      <div className="flex items-center gap-1">
        <span className={cn(
          "w-2 h-2 rounded-full",
          pollRunning ? "bg-status-online animate-pulse" : "bg-muted-foreground/30"
        )} />
        <span className="text-muted-foreground">轮询</span>
      </div>

      {/* SSE status */}
      <div className="flex items-center gap-1">
        {sseStatus === 'connected' ? (
          <Wifi className="h-3 w-3 text-status-online" />
        ) : sseStatus === 'connecting' || sseStatus === 'reconnecting' ? (
          <Loader2 className="h-3 w-3 text-status-warning animate-spin" />
        ) : (
          <WifiOff className="h-3 w-3 text-status-error" />
        )}
        <span className="text-muted-foreground">
          {sseStatus === 'connected' ? '已连接' :
           sseStatus === 'connecting' ? '连接中...' :
           sseStatus === 'reconnecting' ? `重连(${reconnectIn}s)` :
           '断开'}
        </span>
      </div>
    </div>
  )
}
