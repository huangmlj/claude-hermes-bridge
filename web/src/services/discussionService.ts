/**
 * discussionService.ts - 讨论生命周期服务
 *
 * 对应按钮功能：
 * - 开始讨论 (startDiscussion) → API: POST /api/discussion/start
 * - 开始AI对话 (startAI) → API: POST /api/discussion/start-ai
 * - 结束讨论 (endDiscussion) → API: POST /api/discussion/end
 * - 加载讨论 (loadDiscussion) → API: GET /discussions/{filename}
 * - 删除讨论 (deleteDiscussion) → API: POST /api/discussion/delete
 * - 列出讨论 (listDiscussions) → API: POST /api/discussion/list
 */

import type { Discussion, Message } from '@/lib/types'

const BASE = 'http://localhost:8765'

async function post<T>(path: string, body?: object): Promise<T> {
  const res = await fetch(BASE + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
  return res.json()
}

async function get<T>(path: string): Promise<T> {
  const res = await fetch(BASE + path)
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
  return res.json()
}

// ---------------------------------------------------------------------------
// 讨论生命周期
// ---------------------------------------------------------------------------

/**
 * 开始新讨论（创建话题 + 初始化状态）
 */
export async function startDiscussion(topic: string): Promise<{
  success: boolean
  filename: string
  filepath: string
  topic: string
}> {
  return post('/api/discussion/start', { topic })
}

/**
 * 启动 AI 轮询（两个 poll 进程）
 */
export async function startAI(): Promise<{ success: boolean }> {
  return post('/api/discussion/start-ai')
}

/**
 * 结束讨论并归档
 */
export async function endDiscussion(summary?: string): Promise<{
  success: boolean
  archived: boolean
  message_count: number
}> {
  return post('/api/discussion/end', { summary })
}

/**
 * 列出所有讨论
 */
export async function listDiscussions(): Promise<{
  discussions: Discussion[]
}> {
  return post('/api/discussion/list')
}

/**
 * 加载讨论文件（用于继续历史讨论）
 */
export async function loadDiscussion(filename: string): Promise<{
  topic: string
  messages: Message[]
  started_at: string
  ended_at?: string
}> {
  return get(`/discussions/${encodeURIComponent(filename)}`)
}

/**
 * 删除讨论
 */
export async function deleteDiscussion(filename: string): Promise<{
  success: boolean
}> {
  return post('/api/discussion/delete', { filename })
}
