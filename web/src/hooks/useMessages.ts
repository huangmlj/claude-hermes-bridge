import { useState, useCallback, useEffect, useRef, useMemo } from 'react'
import { type Message } from '../lib/api'

export type AuthorFilter = 'all' | 'user' | 'claude' | 'hermes'

export function useMessages(initial: Message[] = []) {
  const [messages, _setMessages] = useState<Message[]>(initial)
  const [filter, setFilter] = useState<AuthorFilter>('all')
  const [search, setSearch] = useState('')
  const [debouncedSearch, setDebouncedSearch] = useState('')
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  // Debounce search updates by 300ms to avoid excessive filtering
  const debouncedSetSearch = useCallback((value: string) => {
    setSearch(value)
    if (debounceRef.current) clearTimeout(debounceRef.current)
    debounceRef.current = setTimeout(() => {
      setDebouncedSearch(value)
    }, 300)
  }, [])

  // Cleanup timeout on unmount
  useEffect(() => {
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
  }, [])

  const add = useCallback((msg: Message) => {
    _setMessages(prev => [...prev, msg])
  }, [])

  const clear = useCallback(() => {
    _setMessages([])
  }, [])

  const setMessages = useCallback((msgs: Message[]) => {
    _setMessages(msgs)
  }, [])

  // Use debouncedSearch for filtering - memoized to avoid recomputation on every render
  const filtered = useMemo(() => messages.filter(msg => {
    if (filter !== 'all' && msg.author !== filter) return false
    if (debouncedSearch && !msg.content.toLowerCase().includes(debouncedSearch.toLowerCase())) return false
    return true
  }), [messages, filter, debouncedSearch])

  return { messages, filtered, filter, setFilter, search, setSearch: debouncedSetSearch, add, clear, setMessages }
}
