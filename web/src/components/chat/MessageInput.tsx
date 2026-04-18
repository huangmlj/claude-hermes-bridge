import { useState, useRef, useEffect, type KeyboardEvent } from 'react'
import { Send, Sparkles, Loader2 } from 'lucide-react'
import { Textarea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

interface MessageInputProps {
  onSend: (content: string) => void
  onStartAI?: () => void
  disabled?: boolean
  loading?: boolean
  placeholder?: string
  className?: string
}

export function MessageInput({ onSend, onStartAI, disabled, loading, placeholder = '输入消息...', className }: MessageInputProps) {
  const [value, setValue] = useState('')
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
      textareaRef.current.style.height = `${textareaRef.current.scrollHeight}px`
    }
  }, [value])

  const handleSend = () => {
    if (!value.trim() || disabled) return
    onSend(value.trim())
    setValue('')
    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto'
    }
  }

  const handleKeyDown = (e: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter 发送，Shift+Enter 换行（符合主流聊天软件直觉）
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      handleSend()
    }
  }

  return (
    <div className={cn("flex items-end gap-2 p-3 border-t", className)}>
      <div className="relative flex-1">
        <Textarea
          ref={textareaRef}
          value={value}
          onChange={e => setValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholder}
          disabled={disabled}
          className="min-h-[40px] max-h-[200px] resize-none pr-12"
          rows={1}
        />
        <span className="absolute bottom-2 right-12 text-xs text-muted-foreground">
          {value.length}/2000
        </span>
      </div>
      <Button
        onClick={handleSend}
        disabled={disabled || !value.trim()}
        size="icon"
        className={loading ? "opacity-70" : ""}
      >
        {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : <Send className="h-4 w-4" />}
      </Button>
      {onStartAI && (
        <Button
          onClick={onStartAI}
          disabled={disabled}
          variant="secondary"
          className={loading ? "opacity-70" : ""}
        >
          {loading ? <Loader2 className="h-4 w-4 mr-1 animate-spin" /> : <Sparkles className="h-4 w-4 mr-1" />}
          AI对话
        </Button>
      )}
    </div>
  )
}
