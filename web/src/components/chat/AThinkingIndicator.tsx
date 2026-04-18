import { cn } from '@/lib/utils'

export function AThinkingIndicator({ className }: { className?: string }) {
  return (
    <div className={cn("flex items-center gap-1 px-4 py-2", className)}>
      <span className="flex gap-1">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="w-2 h-2 rounded-full bg-primary animate-bounce"
            style={{ animationDelay: `${i * 150}ms` }}
          />
        ))}
      </span>
      <span className="text-sm text-muted-foreground ml-2">AI思考中...</span>
    </div>
  )
}
