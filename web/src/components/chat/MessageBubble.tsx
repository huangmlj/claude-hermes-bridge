import { memo, useState, useEffect } from 'react'
import { Copy, Check } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { cn, formatDateTime, safeMarkedParse } from '@/lib/utils'
import type { Message } from '@/lib/api'

interface MessageBubbleProps {
  message: Message
  showAuthor?: boolean
}

export const MessageBubble = memo(function MessageBubble({ message, showAuthor = true }: MessageBubbleProps) {
  const [copied, setCopied] = useState(false)
  const [htmlContent, setHtmlContent] = useState('')

  useEffect(() => {
    safeMarkedParse(message.content).then(setHtmlContent)
  }, [message.content])

  // 代码块复制按钮点击事件（DOM注入后绑定）
  useEffect(() => {
    const container = document.getElementById(`msg-${message.id}`)
    if (!container) return
    const handler = async (e: MouseEvent) => {
      const btn = (e.target as Element).closest('.code-copy-btn') as HTMLButtonElement | null
      if (!btn) return
      const code = decodeURIComponent(btn.dataset.code || '')
      await navigator.clipboard.writeText(code)
      btn.textContent = '已复制!'
      setTimeout(() => { btn.textContent = '复制' }, 2000)
    }
    container.addEventListener('click', handler)
    return () => container.removeEventListener('click', handler)
  }, [message.id, htmlContent])

  const handleCopy = async () => {
    await navigator.clipboard.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  const isUser = message.author === 'user'
  const isSystem = message.author === 'hermes' || message.author === 'claude'

  const authorLabels = {
    user: '我',
    claude: 'Claude',
    hermes: 'Hermes'
  }

  return (
    <div className={cn(
      "flex flex-col",
      isUser ? "items-end" : "items-start"
    )}>
      {showAuthor && isSystem && (
        <Badge variant="secondary" className="mb-1 text-xs">
          {authorLabels[message.author]}
        </Badge>
      )}
      <div className={cn(
        "group relative",
        isUser ? "msg-user" : "msg-ai",
        !isUser && "ml-8"
      )}>
        <div
          id={`msg-${message.id}`}
          className="prose prose-sm max-w-none dark:prose-invert"
          dangerouslySetInnerHTML={{ __html: htmlContent }}
        />
        <div className="absolute -right-2 -top-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <Button
            variant="ghost"
            size="icon"
            className="h-6 w-6"
            onClick={handleCopy}
          >
            {copied ? <Check className="h-3 w-3" /> : <Copy className="h-3 w-3" />}
          </Button>
        </div>
      </div>
      <span className="text-xs text-muted-foreground mt-1 px-1">
        {formatDateTime(message.timestamp)}
      </span>
    </div>
  )
})
