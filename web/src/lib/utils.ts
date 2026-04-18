import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function formatDateTime(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('zh-CN', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
}

export function formatDuration(seconds: number): string {
  if (seconds < 60) return `${seconds}秒`
  if (seconds < 3600) return `${Math.floor(seconds/60)}分钟`
  return `${Math.floor(seconds/3600)}小时${Math.floor((seconds%3600)/60)}分钟`
}

export async function safeMarkedParse(content: string): Promise<string> {
  const { marked } = await import('marked')
  const DOMPurify = (await import('dompurify')).default
  // Remove session_id lines
  const cleaned = content.replace(/session_id:\s*\S+\s*/g, '')
  const html = marked.parse(cleaned) as string
  return DOMPurify.sanitize(html)
}
