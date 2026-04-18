import { MessageList } from './MessageList'
import { MessageInput } from './MessageInput'
import { AThinkingIndicator } from './AThinkingIndicator'
import { Button } from '@/components/ui/button'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { MessageSquare, Square, Sparkles, RefreshCw, FileText, Brain, Lightbulb } from 'lucide-react'
import type { Message } from '@/lib/api'
import type { AuthorFilter } from '@/hooks/useMessages'

interface ChatInterfaceProps {
  messages: Message[]
  allCount: number
  filter: AuthorFilter
  onFilterChange: (filter: AuthorFilter) => void
  search: string
  onSearchChange: (search: string) => void
  onSend: (content: string) => void
  onStartAI?: () => void
  onEnd?: () => void
  currentTopic: string
  pollRunning?: boolean
  aiNames: { claude: string; hermes: string }
  sending?: boolean
  viewingHistory?: boolean
  startingAI?: boolean
  onSummary?: (aiType: 'claude' | 'hermes') => void
  onExport?: () => void
}

export function ChatInterface({
  messages,
  allCount,
  filter,
  onFilterChange,
  search,
  onSearchChange,
  onSend,
  onStartAI,
  onEnd,
  currentTopic,
  pollRunning,
  aiNames,
  sending,
  viewingHistory,
  startingAI,
  onSummary,
  onExport,
}: ChatInterfaceProps) {
  const hasTopic = !!currentTopic

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Action bar */}
      <div className="flex items-center justify-between px-4 py-2 border-b shrink-0">
        <div className="flex items-center gap-2">
          <MessageSquare className="h-4 w-4 text-muted-foreground" />
          <span className="text-sm font-medium">
            {hasTopic ? currentTopic : '新对话'}
          </span>
          {viewingHistory && (
            <span className="text-xs text-muted-foreground">(历史讨论)</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {hasTopic && (pollRunning || startingAI) && (
            <span className="text-xs text-muted-foreground flex items-center gap-1">
              <span className="w-2 h-2 rounded-full bg-status-online animate-pulse" />
              {startingAI ? '正在开启AI轮询...' : `AI对话中 (${aiNames.claude} ↔ ${aiNames.hermes})`}
            </span>
          )}
          {hasTopic && !pollRunning && !startingAI && onStartAI && (
            <Button size="sm" onClick={onStartAI}>
              <Sparkles className="h-4 w-4 mr-1" />
              {viewingHistory ? '继续AI讨论' : '开始AI对话'}
            </Button>
          )}
          {hasTopic && (pollRunning || startingAI) && onEnd && (
            <Button variant="destructive" size="sm" onClick={onEnd}>
              <Square className="h-4 w-4 mr-1" />
              结束
            </Button>
          )}
          {/* Summary & Export */}
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
          {hasTopic && onExport && (
            <Button variant="outline" size="sm" onClick={onExport}>
              <FileText className="h-4 w-4 mr-1" />
              导出
            </Button>
          )}
          <Button variant="ghost" size="icon" onClick={() => window.location.reload()} title="刷新页面">
            <RefreshCw className="h-4 w-4" />
          </Button>
        </div>
      </div>

      {/* Messages */}
      <MessageList
        messages={messages}
        allCount={allCount}
        filter={filter}
        onFilterChange={onFilterChange}
        search={search}
        onSearchChange={onSearchChange}
        viewingHistory={viewingHistory}
      />

      {/* Thinking indicator */}
      {pollRunning && <AThinkingIndicator />}

      {/* Input */}
      <MessageInput
        onSend={onSend}
        onStartAI={onStartAI}
        disabled={sending}
        loading={sending}
        className="shrink-0"
        placeholder={hasTopic ? '输入消息...' : '输入话题开始讨论...'}
      />
    </div>
  )
}
