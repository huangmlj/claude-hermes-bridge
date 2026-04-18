import { useState, useCallback } from 'react'
import { listDiscussions, deleteDiscussion } from '@/services/discussionService'
import type { Discussion } from '@/lib/types'

export function useHistory() {
  const [discussions, setDiscussions] = useState<Discussion[]>([])
  const [loading, setLoading] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    try {
      const data = await listDiscussions()
      setDiscussions(data.discussions)
    } catch (e) {
      console.error('Failed to load discussions:', e)
    } finally {
      setLoading(false)
    }
  }, [])

  const remove = useCallback(async (filename: string) => {
    await deleteDiscussion(filename)
    setDiscussions(prev => prev.filter(d => d.filename !== filename))
  }, [])

  return { discussions, loading, load, remove }
}
