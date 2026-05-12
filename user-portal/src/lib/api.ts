const API_BASE = '/api/v1'

export async function login(email: string): Promise<{ access_token: string; role: string; user_id: string }> {
  const res = await fetch(`${API_BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({ email }),
  })
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Login failed' }))
    throw new Error(err.detail || 'Login failed')
  }
  return res.json()
}

export async function register(email: string, name: string, requestedRole: string = 'citizen') {
  const res = await fetch(`${API_BASE}/auth/register`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, name, requested_role: requestedRole }),
  })
  const data = await res.json()
  if (!res.ok) throw new Error(data.detail || 'Registration failed')
  return data
}

export async function getMe(token: string) {
  const res = await fetch(`${API_BASE}/auth/me`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Unauthorized')
  return res.json()
}

export async function getUsers(token: string, status?: string) {
  const params = status ? `?status=${status}` : ''
  const res = await fetch(`${API_BASE}/admin/users${params}`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch users')
  return res.json()
}

export async function getPendingUsers(token: string) {
  const res = await fetch(`${API_BASE}/admin/access-requests`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch pending users')
  return res.json()
}

export async function approveUser(token: string, userId: string, assignedRole?: string) {
  const res = await fetch(`${API_BASE}/admin/users/${userId}/approve`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ assigned_role: assignedRole }),
  })
  if (!res.ok) throw new Error('Failed to approve user')
  return res.json()
}

export async function rejectUser(token: string, userId: string, reason: string = '') {
  const res = await fetch(`${API_BASE}/admin/users/${userId}/reject`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ reason }),
  })
  if (!res.ok) throw new Error('Failed to reject user')
  return res.json()
}

export async function getRoles(token?: string) {
  const res = await fetch(`${API_BASE}/roles`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  })
  if (!res.ok) throw new Error('Failed to fetch roles')
  return res.json()
}

export async function createRole(token: string, data: { name: string; display_name: string; description: string; permissions: string[] }) {
  const res = await fetch(`${API_BASE}/roles`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to create role')
  return res.json()
}

export async function updateRole(token: string, roleId: string, data: Partial<{ display_name: string; description: string; permissions: string[] }>) {
  const res = await fetch(`${API_BASE}/roles/${roleId}`, {
    method: 'PUT',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
  })
  if (!res.ok) throw new Error('Failed to update role')
  return res.json()
}

export async function deleteRole(token: string, roleId: string) {
  const res = await fetch(`${API_BASE}/roles/${roleId}`, {
    method: 'DELETE',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to delete role')
  return res.json()
}

export async function getPermissions() {
  const res = await fetch(`${API_BASE}/permissions`)
  if (!res.ok) throw new Error('Failed to fetch permissions')
  return res.json()
}

export async function query(question: string, token: string) {
  const res = await fetch(`${API_BASE}/query`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  })
  if (!res.ok) throw new Error('Query failed')
  return res.json()
}

export async function getStats(token: string) {
  const res = await fetch(`${API_BASE}/admin/stats`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to fetch stats')
  return res.json()
}

export async function initRBAC(token: string) {
  const res = await fetch(`${API_BASE}/admin/init-rbac`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to init RBAC')
  return res.json()
}

// ── Conversations ─────────────────────────────────────────────────────────────

export async function listConversations(token: string) {
  const res = await fetch(`${API_BASE}/conversations`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to list conversations')
  return res.json()
}

export async function createConversation(token: string, body: object) {
  const res = await fetch(`${API_BASE}/conversations`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new Error('Failed to create conversation')
  return res.json()
}

export async function getConversationMessages(convId: string, token: string) {
  const res = await fetch(`${API_BASE}/conversations/${convId}/messages`, {
    headers: { Authorization: `Bearer ${token}` },
  })
  if (!res.ok) throw new Error('Failed to get messages')
  return res.json()
}

export async function queryStream(
  question: string,
  token: string,
  conversationId: string | null,
  onToken: (token: string) => void,
  onDone: (done: boolean, latency: number, conv_id: string) => void,
) {
  const res = await fetch(`${API_BASE}/query/stream`, {
    method: 'POST',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
    body: JSON.stringify({ question, conversation_id: conversationId }),
  })

  if (!res.ok) throw new Error('Query stream failed')

  const reader = res.body?.getReader()
  if (!reader) throw new Error('No response body')

  const decoder = new TextDecoder()
  let buffer = ''
  let conv_id = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      try {
        const data = JSON.parse(line.slice(6))
        if (data.token) onToken(data.token)
        if (data.done) onDone(true, data.latency_ms, data.conv_id || '')
        if (data.error) throw new Error(data.error)
        if (data.latency_ms !== undefined && !data.done) conv_id = data.conv_id || ''
      } catch {}
    }
  }
}
