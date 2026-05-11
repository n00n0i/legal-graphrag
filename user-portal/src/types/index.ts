// User & Auth Types
export type UserStatus = 'pending' | 'active' | 'rejected' | 'suspended'

export interface User {
  user_id: string
  email: string
  name: string
  role_id: string
  status: UserStatus
  registered_at?: string
  approved_by?: string
}

export interface PendingUser {
  user_id: string
  email: string
  name: string
  requested_role: string
  registered_at: string
}

export interface Role {
  role_id: string
  name: string
  display_name: string
  description: string
  permissions: string[]
  is_system: boolean
}

export interface Permission {
  permission_id: string
  name: string
  description: string
  category: string
}

export type AccessLevel = 'PUBLIC' | 'INTERNAL' | 'REGULATED' | 'CONFIDENTIAL' | 'CLASSIFIED'

export interface Citation {
  section_id: string
  law_title: string
  excerpt: string
  score: number
}

export interface QueryResponse {
  answer: string
  citations: Citation[]
  sources: string[]
  latency_ms: number
}

export interface AdminStats {
  stats: { law: number; section: number; penalty: number; user: number; role: number; pending_users: number }
  timestamp: string
}
