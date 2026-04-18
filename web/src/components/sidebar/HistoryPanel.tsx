import { useState, useMemo, useCallback, memo } from 'react'
import { Search, Trash2, Clock, MessageSquare } from 'lucide-react'
import { Input } from '@/components/ui/input'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import { Separator } from '@/components/ui/separator'
import { ConfirmDeleteDialog } from '@/components/modals/ConfirmDeleteDialog'
import { cn, formatDateTime, formatDuration } from '@/lib/utils'
import type { Discussion } from '@/lib/api'

interface HistoryPanelProps {
  discussions: Discussion[]
  loading: boolean
  onLoad: (filename: string) => void
  onDelete: (filename: string) => void
  onRefresh: () => void
}

function HistoryPanelInner({ discussions, loading, onLoad, onDelete, onRefresh }: HistoryPanelProps) {
  const [search, setSearch] = useState('')
  const [selected, setSelected] = useState<Set<string>>(new Set())
  const [deleteDialog, setDeleteDialog] = useState<{open: boolean; filenames: string[]; title: string}>({
    open: false,
    filenames: [],
    title: ''
  })

  // Memoize filtered results to avoid recomputation on every render
  const filtered = useMemo(() => discussions.filter(d =>
    d.topic.toLowerCase().includes(search.toLowerCase()) ||
    d.filename.toLowerCase().includes(search.toLowerCase())
  ), [discussions, search])

  // Memoize handlers to prevent child re-renders
  const toggleSelect = useCallback((filename: string) => {
    setSelected(prev => {
      const next = new Set(prev)
      if (next.has(filename)) {
        next.delete(filename)
      } else {
        next.add(filename)
      }
      return next
    })
  }, [])

  const handleDeleteClick = useCallback((filename: string) => {
    const discussion = discussions.find(d => d.filename === filename)
    setDeleteDialog({
      open: true,
      filenames: [filename],
      title: `确定要删除讨论"${discussion?.topic || filename}"吗？`
    })
  }, [discussions])

  const handleBulkDeleteClick = useCallback(() => {
    const titles = Array.from(selected).map(f => {
      const d = discussions.find(d => d.filename === f)
      return d?.topic || f
    })
    setDeleteDialog({
      open: true,
      filenames: Array.from(selected),
      title: `确定要删除 ${selected.size} 个讨论吗？此操作无法撤销。`
    })
  }, [selected, discussions])

  const handleDeleteConfirm = useCallback(() => {
    deleteDialog.filenames.forEach(onDelete)
    setSelected(prev => {
      const next = new Set(prev)
      deleteDialog.filenames.forEach(f => next.delete(f))
      return next
    })
    setDeleteDialog({ open: false, filenames: [], title: '' })
  }, [deleteDialog.filenames, onDelete])

  return (
    <div className="flex flex-col h-full">
      {/* Search */}
      <div className="p-3">
        <div className="relative">
          <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="搜索历史..."
            value={search}
            onChange={e => setSearch(e.target.value)}
            className="pl-8 h-9"
          />
        </div>
      </div>

      <Separator />

      {/* List */}
      <ScrollArea className="flex-1">
        <div className="p-2">
          {loading ? (
            <div className="text-center text-muted-foreground py-8">加载中...</div>
          ) : filtered.length === 0 ? (
            <div className="text-center text-muted-foreground py-8">暂无历史记录</div>
          ) : (
            filtered.map(discussion => (
              <div
                key={discussion.filename}
                className={cn(
                  "flex items-start gap-2 p-2 rounded-md cursor-pointer hover:bg-accent transition-colors",
                  selected.has(discussion.filename) && "bg-accent"
                )}
                onClick={() => onLoad(discussion.filename)}
              >
                <input
                  type="checkbox"
                  checked={selected.has(discussion.filename)}
                  onChange={e => {
                    e.stopPropagation()
                    toggleSelect(discussion.filename)
                  }}
                  className="mt-1"
                />
                <div className="flex-1 min-w-0">
                  <div className="font-medium text-sm truncate">
                    {discussion.topic || '无标题'}
                  </div>
                  <div className="flex items-center gap-2 text-xs text-muted-foreground mt-0.5">
                    <span className="flex items-center gap-1">
                      <MessageSquare className="h-3 w-3" />
                      {discussion.message_count}
                    </span>
                    <span className="flex items-center gap-1">
                      <Clock className="h-3 w-3" />
                      {formatDuration(discussion.duration_seconds)}
                    </span>
                  </div>
                  <div className="text-xs text-muted-foreground mt-0.5">
                    {formatDateTime(discussion.started_at)}
                  </div>
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-7 w-7 shrink-0"
                  onClick={e => {
                    e.stopPropagation()
                    handleDeleteClick(discussion.filename)
                  }}
                >
                  <Trash2 className="h-3 w-3" />
                </Button>
              </div>
            ))
          )}
        </div>
      </ScrollArea>

      {/* Bulk delete */}
      {selected.size > 0 && (
        <div className="p-3 border-t">
          <Button variant="destructive" size="sm" className="w-full" onClick={handleBulkDeleteClick}>
            删除 {selected.size} 项
          </Button>
        </div>
      )}

      {/* Delete confirmation dialog */}
      <ConfirmDeleteDialog
        open={deleteDialog.open}
        onOpenChange={(open) => setDeleteDialog(prev => ({ ...prev, open }))}
        onConfirm={handleDeleteConfirm}
        title="确认删除"
        description={deleteDialog.title}
      />
    </div>
  )
}

// Memoize component to prevent unnecessary re-renders
export const HistoryPanel = memo(HistoryPanelInner)
