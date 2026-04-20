/**
 * App.tsx - 组合层
 *
 * 职责：
 * - 组合 services/hooks/components
 * - SSE 消息处理（去重逻辑）
 * - 乐观更新（发送消息）
 * - 路由视图切换
 *
 * 按钮功能分发：
 * - handleSend → messageService.sendMessage / discussionService.startDiscussion
 * - handleStartAI → discussionService.startAI
 * - handleEnd → discussionService.endDiscussion
 * - handleLoadDiscussion → discussionService.loadDiscussion
 * - handleSummary → exportService.generateSummary
 * - handleExport → exportService.exportDiscussion
 */

import { useState, useCallback, useEffect, useRef } from 'react'
import { Toaster } from './components/ui/toast'
import { ErrorBoundary } from './components/ErrorBoundary'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { useSSE } from './hooks/useSSE'
import { useStatus } from './hooks/useStatus'
import { useHistory } from './hooks/useHistory'
import { useMessages } from './hooks/useMessages'
import type { Message } from './lib/types'
import { downloadTextFile, generateMessageId, makeDownloadFilename } from './lib/utils'
import { ChatInterface } from './components/chat/ChatInterface'
import { Sidebar } from './components/sidebar/Sidebar'
import { HistoryPanel } from './components/sidebar/HistoryPanel'
import { StartDiscussionDialog } from './components/modals/StartDiscussionDialog'
import { TooltipProvider } from './components/ui/tooltip'
import { ToastProvider, useToast } from './components/ui/use-toast'
import * as discussionService from './services/discussionService'
import * as messageService from './services/messageService'
import * as exportService from './services/exportService'

const queryClient = new QueryClient()

function AppContent() {
  const [view, setView] = useState<'chat' | 'history'>('chat')
  const [currentTopic, setCurrentTopic] = useState('')
  const [discussionFilename, setDiscussionFilename] = useState('')
  const [showStartDialog, setShowStartDialog] = useState(false)
  const [sending, setSending] = useState(false)
  const [viewingHistory, setViewingHistory] = useState(false)
  const [startingAI, setStartingAI] = useState(false)
  const [exporting, setExporting] = useState(false)

  // SSE 飞行消息追踪（用于乐观更新去重）
  const inFlightMessages = useRef<Map<string, Message>>(new Map())
  // 历史消息时间戳（用于 resume 去重）
  const lastHistoryTimestampRef = useRef<string | null>(null)
  const startAICalledRef = useRef(false)
  const endingRef = useRef(false)
  const restoredCurrentRef = useRef(false)

  const { status } = useStatus()
  const { discussions, loading: historyLoading, load: loadHistory, remove: deleteDiscussion } = useHistory()
  const { messages, filtered, filter, setFilter, search, setSearch, add: addMessage, remove: removeMessage, clear: clearMessages, setMessages } = useMessages()
  const { toast } = useToast()

  // -------------------------------------------------------------------------
  // SSE 消息处理
  // -------------------------------------------------------------------------
  const handleMessage = useCallback((msg: Message) => {
    // 跳过飞行中消息（乐观更新后通过 SSE 确认时去重）
    const inFlightKey = `${msg.author}:${msg.content}`
    if (inFlightMessages.current.has(inFlightKey)) {
      inFlightMessages.current.delete(inFlightKey)
      return
    }
    // 跳过历史消息（resume 场景防止重复显示）
    if (lastHistoryTimestampRef.current && msg.timestamp <= lastHistoryTimestampRef.current) {
      return
    }
    // SSE 收到新消息说明 AI 轮询已启动
    if (startAICalledRef.current) {
      startAICalledRef.current = false
      setStartingAI(false)
    }
    addMessage(msg)
  }, [addMessage])

  const { status: sseStatus, reconnectIn } = useSSE(handleMessage)

  useEffect(() => {
    if (!currentTopic && status?.discussion_active && status.current_topic) {
      setCurrentTopic(status.current_topic)
      setViewingHistory(false)
    }
  }, [currentTopic, status?.current_topic, status?.discussion_active])

  useEffect(() => {
    if (
      restoredCurrentRef.current ||
      messages.length > 0 ||
      !status?.discussion_active ||
      !status.current_topic ||
      !status.current_messages
    ) {
      return
    }

    restoredCurrentRef.current = true
    messageService.getCurrentMessages()
      .then(res => {
        setMessages(res.messages)
        const lastTimestamp = res.messages.length > 0 ? res.messages[res.messages.length - 1].timestamp : null
        lastHistoryTimestampRef.current = lastTimestamp
        localStorage.setItem('lastEventId', String(res.messages.length))
      })
      .catch(e => {
        restoredCurrentRef.current = false
        const msg = e instanceof Error ? e.message : String(e)
        toast({ title: '恢复当前讨论失败', description: msg, variant: 'destructive' })
      })
  }, [messages.length, setMessages, status?.current_messages, status?.current_topic, status?.discussion_active, toast])

  // -------------------------------------------------------------------------
  // 发送消息
  // -------------------------------------------------------------------------
  const handleSend = useCallback(async (content: string) => {
    if (!currentTopic) {
      // 开始新讨论
      setSending(true)
      setViewingHistory(false)
      setStartingAI(true)
      startAICalledRef.current = true
      lastHistoryTimestampRef.current = null

      try {
        const result = await discussionService.startDiscussion(content)
        setCurrentTopic(result.topic)
        setDiscussionFilename(result.filename)
        clearMessages()
        const timestamp = new Date().toISOString()
        addMessage({
          id: generateMessageId('user', content, timestamp),
          layer: 1,
          author: 'user',
          content,
          timestamp
        })
        await discussionService.startAI()
        toast({ title: '话题已创建', description: 'AI 对话已开始' })
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        startAICalledRef.current = false
        setStartingAI(false)
        toast({ title: '创建话题失败', description: msg, variant: 'destructive' })
      } finally {
        setSending(false)
      }
    } else {
      // 发送消息（乐观更新）
      setSending(true)
      const timestamp = new Date().toISOString()
      const msg = {
        id: generateMessageId('user', content, timestamp),
        layer: 0,
        author: 'user' as const,
        content,
        timestamp
      }
      inFlightMessages.current.set(`user:${content}`, msg)
      addMessage(msg)

      try {
        await messageService.sendMessage(content)
      } catch (e: unknown) {
        // 发送失败，移除飞行中标记
        inFlightMessages.current.delete(`user:${content}`)
        removeMessage(msg.id)
        const errMsg = e instanceof Error ? e.message : String(e)
        toast({ title: '发送失败', description: errMsg, variant: 'destructive' })
      } finally {
        setSending(false)
      }
    }
  }, [currentTopic, clearMessages, addMessage, removeMessage, toast])

  // -------------------------------------------------------------------------
  // 启动 AI
  // -------------------------------------------------------------------------
  const handleStartAI = useCallback(async () => {
    if (!currentTopic) {
      setShowStartDialog(true)
    } else {
      setViewingHistory(false)
      setStartingAI(true)
      startAICalledRef.current = true

      try {
        if (discussionFilename) {
          localStorage.removeItem('lastEventId')
        }
        lastHistoryTimestampRef.current = null
        await discussionService.startAI()
        toast({ title: discussionFilename ? '已恢复讨论' : 'AI 对话已启动', description: 'AI 对话继续中' })
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : String(e)
        startAICalledRef.current = false
        setViewingHistory(true)
        setStartingAI(false)
        toast({ title: '启动失败', description: msg, variant: 'destructive' })
      }
    }
  }, [currentTopic, discussionFilename, toast])

  // -------------------------------------------------------------------------
  // 结束讨论
  // -------------------------------------------------------------------------
  const handleEnd = useCallback(async () => {
    if (!currentTopic || endingRef.current) return
    endingRef.current = true

    try {
      await discussionService.endDiscussion()
      // 重置所有相关状态
      setCurrentTopic('')
      setDiscussionFilename('')
      setViewingHistory(false)
      clearMessages()
      localStorage.removeItem('lastEventId')
      lastHistoryTimestampRef.current = null
      toast({ title: 'AI 对话已结束' })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      toast({ title: '结束失败', description: msg, variant: 'destructive' })
    } finally {
      endingRef.current = false
    }
  }, [currentTopic, toast, clearMessages])

  // -------------------------------------------------------------------------
  // 加载讨论
  // -------------------------------------------------------------------------
  const handleLoadDiscussion = useCallback(async (filename: string) => {
    try {
      const res = await discussionService.loadDiscussion(filename)
      setMessages(res.messages)
      const lastTimestamp = res.messages.length > 0 ? res.messages[res.messages.length - 1].timestamp : null
      lastHistoryTimestampRef.current = lastTimestamp
      localStorage.setItem('lastEventId', String(res.messages.length))
      setCurrentTopic(res.topic)
      setDiscussionFilename(filename)
      setViewingHistory(true)
      setView('chat')
      toast({ title: '已加载讨论', description: res.topic })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      toast({ title: '加载失败', description: msg, variant: 'destructive' })
    }
  }, [setMessages, toast])

  // -------------------------------------------------------------------------
  // 总结
  // -------------------------------------------------------------------------
  const handleSummary = useCallback(async (aiType: 'claude' | 'hermes') => {
    if (!currentTopic) return
    const content = messages.map(m => `[${m.author}]: ${m.content}`).join('\n')
    try {
      const result = await exportService.generateSummary(currentTopic, aiType, content)
      toast({ title: '总结已生成', description: `保存至 ${result.path}` })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      toast({ title: '总结失败', description: msg, variant: 'destructive' })
    }
  }, [currentTopic, messages, toast])

  // -------------------------------------------------------------------------
  // 导出
  // -------------------------------------------------------------------------
  const handleExport = useCallback(async () => {
    if (!currentTopic) {
      toast({ title: '无法导出', description: '当前没有讨论话题。', variant: 'destructive' })
      return
    }
    if (messages.length === 0) {
      toast({ title: '无法导出', description: '当前讨论还没有消息。', variant: 'destructive' })
      return
    }

    const content = messages.map(m => `**${m.author}**: ${m.content}`).join('\n\n')
    setExporting(true)
    try {
      toast({ title: '正在导出', description: '正在生成 Markdown 文件...' })
      const result = await exportService.exportDiscussion(currentTopic, content)
      toast({ title: '已导出', description: `已保存至 ${result.path}` })
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : String(e)
      toast({ title: '导出失败', description: msg, variant: 'destructive' })
    } finally {
      setExporting(false)
    }
  }, [currentTopic, messages, toast])

  // 挂载时加载历史
  useEffect(() => { loadHistory() }, [loadHistory])

  return (
    <div className="flex h-screen">
      <Sidebar
        view={view}
        onViewChange={setView}
        sseStatus={sseStatus}
        reconnectIn={reconnectIn}
        pollRunning={status?.poll_running}
        currentTopic={currentTopic || status?.current_topic}
        messageCount={messages.length || status?.current_messages || 0}
        viewingHistory={viewingHistory}
      />
      <main className="flex-1 overflow-hidden">
        {view === 'history' ? (
          <HistoryPanel
            discussions={discussions}
            loading={historyLoading}
            activeFilename={discussionFilename}
            onLoad={handleLoadDiscussion}
            onDelete={deleteDiscussion}
            onRefresh={loadHistory}
          />
        ) : (
          <ChatInterface
            messages={filtered}
            allCount={messages.length}
            filter={filter}
            onFilterChange={setFilter}
            search={search}
            onSearchChange={setSearch}
            onSend={handleSend}
            onStartAI={handleStartAI}
            onEnd={handleEnd}
            currentTopic={currentTopic}
            pollRunning={status?.poll_running}
            aiNames={{ claude: status ? 'Claude' : '...', hermes: status ? 'Hermes' : '...' }}
            sending={sending}
            viewingHistory={viewingHistory}
            startingAI={startingAI}
            exporting={exporting}
            onSummary={handleSummary}
            onExport={handleExport}
          />
        )}
        <Toaster />
      </main>
      <StartDiscussionDialog
        open={showStartDialog}
        onOpenChange={setShowStartDialog}
        onStart={async (topic) => {
          setSending(true)
          setStartingAI(true)
          startAICalledRef.current = true
          lastHistoryTimestampRef.current = null

          try {
            const result = await discussionService.startDiscussion(topic)
            setCurrentTopic(result.topic)
            setDiscussionFilename(result.filename)
            clearMessages()
            setViewingHistory(false)
            const timestamp = new Date().toISOString()
            addMessage({
              id: generateMessageId('user', topic, timestamp),
              layer: 1,
              author: 'user',
              content: topic,
              timestamp
            })
            await discussionService.startAI()
            toast({ title: '话题已创建', description: 'AI 对话已开始' })
          } catch (e: unknown) {
            const msg = e instanceof Error ? e.message : String(e)
            startAICalledRef.current = false
            setStartingAI(false)
            setCurrentTopic('')
            toast({ title: '创建话题失败', description: msg, variant: 'destructive' })
          } finally {
            setSending(false)
            setShowStartDialog(false)
          }
        }}
      />
    </div>
  )
}

export default function App() {
  return (
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <ToastProvider>
          <TooltipProvider>
            <AppContent />
          </TooltipProvider>
        </ToastProvider>
      </QueryClientProvider>
    </ErrorBoundary>
  )
}
