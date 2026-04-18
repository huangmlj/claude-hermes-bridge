import { useState } from 'react'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'

interface StartDiscussionDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
  onStart: (topic: string) => void
}

export function StartDiscussionDialog({ open, onOpenChange, onStart }: StartDiscussionDialogProps) {
  const [topic, setTopic] = useState('')

  const handleStart = () => {
    if (topic.trim()) {
      onStart(topic.trim())
      setTopic('')
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>开始新讨论</DialogTitle>
          <DialogDescription>
            输入话题开始与AI的对话
          </DialogDescription>
        </DialogHeader>
        <div className="py-4">
          <Input
            placeholder="输入话题..."
            value={topic}
            onChange={e => setTopic(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && handleStart()}
            autoFocus
          />
        </div>
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            取消
          </Button>
          <Button onClick={handleStart} disabled={!topic.trim()}>
            开始
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
