/**
 * exportService.ts - 导出/总结服务
 *
 * 对应按钮功能：
 * - 导出 (exportDiscussion) → API: POST /api/export
 * - 总结 - Claude (generateSummary) → API: POST /api/summary
 * - 总结 - Hermes (generateSummary) → API: POST /api/summary
 */

import { getApiBase } from '@/lib/api'

async function post<T>(path: string, body?: object): Promise<T> {
  const res = await fetch(getApiBase() + path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  })
  if (!res.ok) throw new Error(`${res.status}: ${res.statusText}`)
  return res.json()
}

/**
 * 导出讨论为 Markdown 文件
 * @param topic 讨论话题
 * @param content Markdown 格式的讨论内容
 */
export async function exportDiscussion(topic: string, content: string): Promise<{
  success: boolean
  path: string
}> {
  return post('/api/export', { topic, content })
}

/**
 * AI 生成讨论总结
 * @param topic 讨论话题
 * @param aiType "claude" | "hermes"
 * @param messagesContent 消息内容
 */
export async function generateSummary(
  topic: string,
  aiType: 'claude' | 'hermes',
  messagesContent: string
): Promise<{
  success: boolean
  path: string
  summary: string
}> {
  return post('/api/summary', {
    topic,
    ai_type: aiType,
    messages_content: messagesContent,
  })
}
