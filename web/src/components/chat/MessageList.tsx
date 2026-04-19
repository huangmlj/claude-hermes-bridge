import { useRef, useEffect, useCallback } from 'react'
import { useVirtualizer } from '@tanstack/react-virtual'
import { Search, X } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { MessageBubble } from './MessageBubble'
import type { Message } from '@/lib/api'
import type { AuthorFilter } from '@/hooks/useMessages'

interface MessageListProps {
  messages: Message[]
  allCount: number
  filter: AuthorFilter
  onFilterChange: (filter: AuthorFilter) => void
  search: string
  onSearchChange: (search: string) => void
  viewingHistory?: boolean
}

export function MessageList({
  messages,
  allCount,
  filter,
  onFilterChange,
  search,
  onSearchChange,
  viewingHistory,
}: MessageListProps) {
  const parentRef = useRef<HTMLDivElement>(null)

  // Virtual list for messages - only renders visible items
  const virtualizer = useVirtualizer({
    count: messages.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => 120, // Estimated average message height
    overscan: 5, // Render 5 extra items above/below viewport
  })

  // Auto-scroll to bottom when new messages arrive
  // 使用 virtualizer.scrollToIndex，自动处理动态高度测量后的补偿
  const scrollToBottom = useCallback(() => {
    if (messages.length > 0) {
      virtualizer.scrollToIndex(messages.length - 1, { align: 'end', behavior: 'smooth' })
    }
  }, [messages.length, virtualizer])

  useEffect(() => {
    scrollToBottom()
  }, [messages.length, scrollToBottom])

  const filters: { value: AuthorFilter; label: string }[] = [
    { value: 'all', label: '全部' },
    { value: 'user', label: '我' },
    { value: 'claude', label: 'Claude' },
    { value: 'hermes', label: 'Hermes' },
  ]

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* Filter and search bar */}
      <div className="flex items-center gap-2 p-3 border-b shrink-0">
        <div className="flex gap-1">
          {filters.map(f => (
            <Badge
              key={f.value}
              variant={filter === f.value ? 'default' : 'secondary'}
              className="cursor-pointer"
              onClick={() => onFilterChange(f.value)}
            >
              {f.label}
            </Badge>
          ))}
        </div>
        <div className="relative flex-1 max-w-[200px]">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索消息..."
            value={search}
            onChange={e => onSearchChange(e.target.value)}
            className="pl-8 h-8"
          />
          {search && (
            <button
              className="absolute right-2 top-1/2 -translate-y-1/2"
              onClick={() => onSearchChange('')}
            >
              <X className="h-4 w-4 text-muted-foreground" />
            </button>
          )}
        </div>
        <span className="text-xs text-muted-foreground">
          {messages.length}/{allCount}
        </span>
      </div>

      {/* Virtualized Messages */}
      <div
        ref={parentRef}
        className="flex-1 min-h-0 overflow-y-auto contain-content"
      >
        {messages.length === 0 ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground text-center p-4">
            {allCount === 0 ? (
              viewingHistory ? (
                <>
                  <p className="mb-2">历史讨论为空</p>
                  <p className="text-sm">点击上方「开始AI对话」继续讨论</p>
                </>
              ) : (
                '暂无消息，开始对话吧'
              )
            ) : (
              '没有符合筛选条件的消息'
            )}
          </div>
        ) : (
          <div
            style={{
              height: `${virtualizer.getTotalSize()}px`,
              width: '100%',
              position: 'relative',
            }}
          >
            {virtualizer.getVirtualItems().map(virtualItem => (
              <div
                key={virtualItem.key}
                data-index={virtualItem.index}
                ref={virtualizer.measureElement}
                style={{
                  position: 'absolute',
                  top: 0,
                  left: 0,
                  width: '100%',
                  transform: `translateY(${virtualItem.start}px)`,
                  padding: '1rem',
                }}
              >
                <MessageBubble message={messages[virtualItem.index]} />
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
