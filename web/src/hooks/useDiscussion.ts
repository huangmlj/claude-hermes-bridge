/**
 * useDiscussion.ts - 讨论生命周期状态管理
 *
 * 管理状态：
 * - currentTopic: 当前讨论话题
 * - discussionFilename: 当前讨论文件名
 * - viewingHistory: 是否正在查看历史讨论
 * - startingAI: 是否正在启动 AI 轮询
 * - ending: 是否正在结束讨论
 */

import { useState, useCallback, useRef } from 'react'
import type { Message } from '@/lib/types'
import * as discussionService from '@/services/discussionService'
import * as messageService from '@/services/messageService'
import { useToast } from '@/components/ui/use-toast'

export interface UseDiscussionReturn {
  // 状态
  currentTopic: string
  discussionFilename: string
  viewingHistory: boolean
  startingAI: boolean
  ending: boolean

  // 消息列表操作
  setCurrentTopic: (topic: string) => void
  setDiscussionFilename: (filename: string) => void
  setMessages: (messages: Message[]) => void
  clearMessages: () => void
  addMessage: (msg: Message) => void

  // 操作
  handleSend: (content: string) => Promise<void>
  handleStartAI: () => Promise<void>
  handleEnd: () => Promise<void>
  handleLoadDiscussion: (filename: string) => Promise<void>
}

export function useDiscussion(
  messages: Message[],
  setMessages: (msgs: Message[]) => void,
  addMessage: (msg: Message) => void,
  clearMessages: () => void,
): UseDiscussionReturn {
  const [currentTopic, setCurrentTopic] = useState('')
  const [discussionFilename, setDiscussionFilename] = useState('')
  const [viewingHistory, setViewingHistory] = useState(false)
  const [startingAI, setStartingAI] = useState(false)
  const [ending, setEnding] = useState(false)

  const startAICalledRef = useRef(false)
  const endingRef = useRef(false)
  const lastHistoryTimestampRef = useRef<string | null>(null)
  const { toast } = useToast()

  // -------------------------------------------------------------------------
  // 发送消息
  // -------------------------------------------------------------------------
  const handleSend = useCallback(async (content: string) => {
    if (!currentTopic) {
      // 开始新讨论
      setStartingAI(true)
      startAICalledRef.current = true
      lastHistoryTimestampRef.current = null

      try {
        const result = await discussionService.startDiscussion(content)
        setCurrentTopic(result.topic)
        clearMessages()
        addMessage({
          layer: 1,
          author: 'user',
          content,
          timestamp: new Date().toISOString(),
        })
        await discussionService.startAI()
        toast({ title: '话题已创建', description: 'AI 对话已开始' })
      } catch (e: any) {
        startAICalledRef.current = false
        setStartingAI(false)
        toast({ title: '创建话题失败', description: e.message, variant: 'destructive' })
      }
    } else {
      // 发送普通消息
      try {
        await messageService.sendMessage(content)
        // 消息通过 SSE 推送更新，这里不需要手动添加
      } catch (e: any) {
        toast({ title: '发送失败', description: e.message, variant: 'destructive' })
      }
    }
  }, [currentTopic, clearMessages, addMessage, toast])

  // -------------------------------------------------------------------------
  // 启动 AI
  // -------------------------------------------------------------------------
  const handleStartAI = useCallback(async () => {
    if (!currentTopic) {
      // 无话题时，UI 会显示开始讨论弹窗（由 App 层处理）
      return
    }

    setViewingHistory(false)
    setStartingAI(true)
    startAICalledRef.current = true

    try {
      if (discussionFilename) {
        // 继续历史讨论，清除 SSE checkpoint
        localStorage.removeItem('lastEventId')
      }
      // 清除历史时间戳（用于 resume 去重）
      lastHistoryTimestampRef.current = null

      await discussionService.startAI()
      toast({
        title: discussionFilename ? '已恢复讨论' : 'AI 对话已启动',
        description: 'AI 对话继续中',
      })
    } catch (e: any) {
      startAICalledRef.current = false
      setViewingHistory(true)
      setStartingAI(false)
      toast({ title: '启动失败', description: e.message, variant: 'destructive' })
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
      toast({ title: 'AI 对话已结束' })
    } catch (e: any) {
      toast({ title: '结束失败', description: e.message, variant: 'destructive' })
    } finally {
      endingRef.current = false
    }
  }, [toast])

  // -------------------------------------------------------------------------
  // 加载讨论
  // -------------------------------------------------------------------------
  const handleLoadDiscussion = useCallback(async (filename: string) => {
    try {
      const res = await discussionService.loadDiscussion(filename)

      // 批量更新消息列表
      setMessages(res.messages)

      // 记录最后一条历史消息的时间戳，用于 resume 去重
      const lastTimestamp =
        res.messages.length > 0
          ? res.messages[res.messages.length - 1].timestamp
          : null
      lastHistoryTimestampRef.current = lastTimestamp

      setCurrentTopic(res.topic)
      setDiscussionFilename(filename)
      setViewingHistory(true)

      toast({ title: '已加载讨论', description: res.topic })
    } catch (e: any) {
      toast({ title: '加载失败', description: e.message, variant: 'destructive' })
    }
  }, [setMessages, toast])

  return {
    currentTopic,
    discussionFilename,
    viewingHistory,
    startingAI,
    ending,

    setCurrentTopic,
    setDiscussionFilename,
    setMessages,
    clearMessages,
    addMessage,

    handleSend,
    handleStartAI,
    handleEnd,
    handleLoadDiscussion,
  }
}
