import { MessageSquare, RefreshCw, FileText, Brain, Lightbulb } from 'lucide-react'
import { ServiceStatus } from './ServiceStatus'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import type { SSEStatus } from '@/hooks/useSSE'

interface HeaderProps {
  topic: string
  topicActive: boolean
  pollRunning?: boolean
  sseStatus: SSEStatus
  reconnectIn?: number
  onSummary?: (aiType: 'claude' | 'hermes') => void
  onExport?: () => void
  hasTopic?: boolean
}

export function Header({ topic, topicActive, pollRunning, sseStatus, reconnectIn, onSummary, onExport, hasTopic }: HeaderProps) {
  return (
    <header className="flex items-center justify-between px-4 py-3 border-b bg-card">
      <div className="flex items-center gap-3 min-w-0">
        <MessageSquare className="h-5 w-5 text-primary shrink-0" />
        <div className="flex items-center min-w-0">
          {topicActive && (
            <span className="text-xs text-muted-foreground mr-2 shrink-0">
              当前话题：
            </span>
          )}
          <span className="text-sm font-semibold truncate">
            {topic || '讨论话题'}
          </span>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {hasTopic && onSummary && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <FileText className="h-4 w-4 mr-1" />
                总结
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => onSummary('claude')}>
                <Brain className="h-4 w-4 mr-2" />
                Claude 总结
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => onSummary('hermes')}>
                <Lightbulb className="h-4 w-4 mr-2" />
                Hermes 总结
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}

        <Button variant="ghost" size="icon" onClick={() => window.location.reload()} title="刷新页面">
          <RefreshCw className="h-4 w-4" />
        </Button>

        <ServiceStatus
          serverOnline={true}
          pollRunning={pollRunning || false}
          sseStatus={sseStatus}
          reconnectIn={reconnectIn}
        />
      </div>
    </header>
  )
}
