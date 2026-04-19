export interface Message {
  id: string
  layer: number
  author: 'user' | 'claude' | 'hermes'
  content: string
  timestamp: string
}

export interface Discussion {
  filename: string
  topic: string
  message_count: number
  started_at: string
  ended_at?: string
  preview: string
  duration_seconds: number
  size: number
  modified: string
  sort_key: string
}

export interface ServerStatus {
  online: boolean
  current_messages: number
  current_layer: number
  current_topic: string
  last_write_by: string
  discussions_count: number
  discussion_active: boolean
  discussion_started: boolean
  poll_running: boolean
  timestamp: string
}

export interface AIModels {
  claude: string
  hermes: string
}
