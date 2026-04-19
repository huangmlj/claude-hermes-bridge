import { type ClassValue, clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

export function generateMessageId(author: string, content: string, timestamp: string): string {
  const raw = `${author}:${content}:${timestamp}`
  let hash = 0
  for (let i = 0; i < raw.length; i++) {
    const char = raw.charCodeAt(i)
    hash = ((hash << 5) - hash) + char
    hash = hash & hash
  }
  return Math.abs(hash).toString(16).padStart(12, '0')
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

  // 自定义渲染器：为代码块添加一键复制按钮
  const renderer = {
    code({ text, lang }: { text: string; lang?: string }) {
      const langClass = lang ? ` class="language-${lang}"` : ''
      const escaped = text
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
      return `<div class="code-block-wrapper relative group">
        <button class="code-copy-btn absolute top-2 right-2 opacity-0 group-hover:opacity-100 transition-opacity bg-muted hover:bg-muted/80 text-muted-foreground text-xs px-2 py-1 rounded cursor-pointer" data-code="${encodeURIComponent(text)}">复制</button>
        <pre><code${langClass}>${escaped}</code></pre>
      </div>`
    }
  }

  marked.use({ renderer })

  // Remove session_id lines
  const cleaned = content.replace(/session_id:\s*\S+\s*/g, '')
  const html = marked.parse(cleaned) as string
  return DOMPurify.sanitize(html, {
    ADD_TAGS: ['button'],
    ADD_ATTR: ['data-code'],
  })
}
