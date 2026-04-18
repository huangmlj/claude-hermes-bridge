import { Zap, MessageSquare, History } from 'lucide-react'
import { HistoryPanel } from './HistoryPanel'
import { StatusBar } from './StatusBar'
import { cn } from '@/lib/utils'
import type { SSEStatus } from '@/hooks/useSSE'
import type { Discussion } from '@/lib/api'

interface SidebarProps {
  view: 'chat' | 'history'
  onViewChange: (view: 'chat' | 'history') => void
  sseStatus: SSEStatus
  reconnectIn?: number
  pollRunning?: boolean
  discussions: Discussion[]
  onLoad: (filename: string) => void
  onDelete: (filename: string) => void
  onRefreshHistory: () => void
}

export function Sidebar({
  view,
  onViewChange,
  sseStatus,
  reconnectIn,
  pollRunning,
  discussions,
  onLoad,
  onDelete,
  onRefreshHistory,
}: SidebarProps) {
  return (
    <aside className="w-64 border-r flex flex-col bg-card h-full">
      {/* Brand */}
      <div className="flex items-center gap-2 px-4 py-4 border-b">
        <Zap className="h-5 w-5 text-primary fill-primary" />
        <span className="font-semibold text-sm">Hermes × Claude</span>
      </div>

      {/* Status indicators */}
      <div className="px-4 py-3 border-b space-y-1">
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "w-2 h-2 rounded-full",
                reconnectIn !== undefined && reconnectIn > 0 ? "animate-pulse" : ""
              )}
              style={{
                backgroundColor: reconnectIn !== undefined && reconnectIn > 0
                  ? 'var(--status-connecting)'
                  : sseStatus === 'connected'
                  ? 'var(--status-online)'
                  : 'var(--status-offline)'
              }}
            />
            <span>服务器</span>
          </div>
          <span>{sseStatus === 'connected' ? '已链接' : sseStatus === 'connecting' ? '连接中...' : '未链接'}</span>
        </div>
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <div className="flex items-center gap-2">
            <span
              className={cn(
                "w-2 h-2 rounded-full",
                reconnectIn !== undefined && reconnectIn > 0 ? "animate-pulse" : ""
              )}
              style={{
                backgroundColor: reconnectIn !== undefined && reconnectIn > 0
                  ? 'var(--status-connecting)'
                  : pollRunning
                  ? 'var(--status-online)'
                  : 'var(--status-offline)'
              }}
            />
            <span>轮询</span>
          </div>
          <span>{reconnectIn !== undefined && reconnectIn > 0 ? `${reconnectIn}s后重连` : pollRunning ? '运行中' : '空闲'}</span>
        </div>
      </div>

      {/* Nav tabs */}
      <div className="flex border-b">
        <button
          className={cn(
            "flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors",
            view === 'chat'
              ? "text-primary border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground"
          )}
          onClick={() => onViewChange('chat')}
        >
          <MessageSquare className="h-4 w-4" />
          聊天
        </button>
        <button
          className={cn(
            "flex-1 flex items-center justify-center gap-2 py-3 text-sm transition-colors",
            view === 'history'
              ? "text-primary border-b-2 border-primary"
              : "text-muted-foreground hover:text-foreground"
          )}
          onClick={() => onViewChange('history')}
        >
          <History className="h-4 w-4" />
          历史
        </button>
      </div>

      {/* Content */}
      <div className="flex-1 overflow-hidden">
        {view === 'history' ? (
          <HistoryPanel
            discussions={discussions}
            loading={false}
            onLoad={onLoad}
            onDelete={onDelete}
            onRefresh={onRefreshHistory}
          />
        ) : (
          <div className="p-4 text-center text-muted-foreground text-sm">
            <MessageSquare className="h-8 w-8 mx-auto mb-2 opacity-50" />
            <p>当前对话</p>
          </div>
        )}
      </div>

      {/* Status bar */}
      <StatusBar sseStatus={sseStatus} reconnectIn={reconnectIn} />
    </aside>
  )
}
