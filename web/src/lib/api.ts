/**
 * api.ts - SSE 连接工具 + 类型重导出
 *
 * API 调用已迁移到 services/ 目录：
 * - services/discussionService.ts - 讨论生命周期
 * - services/messageService.ts    - 消息发送
 * - services/exportService.ts     - 导出/总结
 */

import type { Message, Discussion, ServerStatus, AIModels } from './types'

// 从环境变量读取 BASE URL，优先使用 Vite 的代理模式（开发环境）
// 生产环境通过 .env.local 设置 VITE_API_BASE_URL
const BASE = import.meta.env.VITE_API_BASE_URL || ''
// 如果 BASE 为空（开发环境使用代理），回退到直接 URL
const FALLBACK_BASE = import.meta.env.VITE_BACKEND_URL || 'http://localhost:8765'
const API_BASE = BASE || FALLBACK_BASE

// ---------------------------------------------------------------------------
// SSE
// ---------------------------------------------------------------------------

export function createSSE(
  lastEventId: number,
  onMessage: (msg: Message, id: string) => void,
  onError: () => void
) {
  const url = `${API_BASE}/api/events${lastEventId ? `?lastEventId=${lastEventId}` : ''}`
  const es = new EventSource(url)

  es.onmessage = (e) => {
    try {
      const data = JSON.parse(e.data)
      onMessage(data, e.lastEventId)
    } catch (err) {
      console.error('Failed to parse SSE message:', err, 'data:', e.data)
    }
  }
  es.onerror = onError

  return es
}

export function getDiscussionFile(filename: string) {
  return fetch(`${API_BASE}/discussions/${encodeURIComponent(filename)}`)
}

// ---------------------------------------------------------------------------
// 工具函数：导出 API_BASE 供 services 使用
// ---------------------------------------------------------------------------
export function getApiBase() {
  return API_BASE
}

// ---------------------------------------------------------------------------
// 类型重导出（保持向后兼容）
// ---------------------------------------------------------------------------
export type { Message, Discussion, ServerStatus, AIModels }
