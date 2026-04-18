/**
 * api.ts - SSE 连接工具 + 类型重导出
 *
 * API 调用已迁移到 services/ 目录：
 * - services/discussionService.ts - 讨论生命周期
 * - services/messageService.ts    - 消息发送
 * - services/exportService.ts     - 导出/总结
 */

import type { Message, Discussion, ServerStatus, AIModels } from './types'

const BASE = 'http://localhost:8765'

// ---------------------------------------------------------------------------
// SSE
// ---------------------------------------------------------------------------

export function createSSE(
  lastEventId: number,
  onMessage: (msg: Message, id: string) => void,
  onError: () => void
) {
  const url = `${BASE}/api/events${lastEventId ? `?lastEventId=${lastEventId}` : ''}`
  const es = new EventSource(url)

  es.onmessage = (e) => {
    const data = JSON.parse(e.data)
    onMessage(data, e.lastEventId)
  }
  es.onerror = onError

  return es
}

export function getDiscussionFile(filename: string) {
  return fetch(`${BASE}/discussions/${encodeURIComponent(filename)}`)
}

// ---------------------------------------------------------------------------
// 类型重导出（保持向后兼容）
// ---------------------------------------------------------------------------
export type { Message, Discussion, ServerStatus, AIModels }
