/**
 * messageService.ts - 消息发送服务
 *
 * 对应按钮功能：
 * - 发送消息 (sendMessage) → API: POST /api/message
 */

import type { Message } from '@/lib/types'

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

/**
 * 发送消息（追加到 bridge.jsonl）
 * @param content 消息内容
 * @param author 作者（默认为 user）
 */
export async function sendMessage(
  content: string,
  author: string = 'user'
): Promise<{ success: boolean; entry: Message }> {
  return post('/api/message', { content, author })
}
