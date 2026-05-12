import { useState, useEffect, createContext, useContext } from 'react'
import { BrowserRouter, Routes, Route, Navigate, Link, useNavigate, useLocation } from 'react-router-dom'
import { User, UserStatus } from './types'
import RequestApiKeyPage from './pages/RequestApiKeyPage'
import MyApiKeysPage from './pages/MyApiKeysPage'
import MyDocAccessPage from './pages/MyDocAccessPage'

// ─── Auth Context ─────────────────────────────────────────────────────────────
interface AuthContextType {
  user: User | null
  token: string | null
  login: (token: string, user: User) => void
  logout: () => void
  isAdmin: boolean
}

const AuthContext = createContext<AuthContextType>({
  user: null,
  token: null,
  login: () => {},
  logout: () => {},
  isAdmin: false,
})

function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

// ─── Layout ───────────────────────────────────────────────────────────────────
function Sidebar() {
  const { user, logout, isAdmin } = useAuth()
  const location = useLocation()

  const navItems = [
    { path: '/chat', label: '💬 ถาม-ตอบกฎหมาย', icon: '💬' },
    { path: '/request-api-key', label: '🔑 ขอ API Key', icon: '🔑' },
    { path: '/my-api-keys', label: '🔑 My API Keys', icon: '🔑' },
    { path: '/my-doc-access', label: '📋 เอกสารที่เข้าถึงได้', icon: '📋' },
  ]

  return (
    <div className="w-64 bg-dark-200 h-screen flex flex-col border-r border-slate-700">
      {/* Logo */}
      <div className="p-6 border-b border-slate-700">
        <h1 className="text-xl font-bold text-primary-400">⚖️ Legal GraphRAG</h1>
        <p className="text-xs text-slate-400 mt-1">Graph Knowledge + RAG for Thai Laws</p>
      </div>

      {/* Nav */}
      <nav className="flex-1 p-4 space-y-1">
        {navItems.map(item => {
          if (item.adminOnly && !isAdmin) return null
          const active = location.pathname === item.path
          return (
            <Link
              key={item.path}
              to={item.path}
              className={`flex items-center gap-3 px-4 py-3 rounded-lg transition-colors ${
                active ? 'bg-primary-600 text-white' : 'text-slate-300 hover:bg-dark-100'
              }`}
            >
              <span>{item.icon}</span>
              <span className="text-sm font-medium">{item.label}</span>
            </Link>
          )
        })}
      </nav>

      {/* User */}
      <div className="p-4 border-t border-slate-700">
        <div className="flex items-center gap-3 mb-3">
          <div className="w-8 h-8 bg-primary-600 rounded-full flex items-center justify-center text-sm font-bold">
            {user?.name?.charAt(0) || 'U'}
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-sm font-medium truncate">{user?.name || 'User'}</p>
            <p className="text-xs text-slate-400">{user?.role_id}</p>
          </div>
        </div>
        <button onClick={logout} className="w-full btn-secondary text-sm py-1.5">
          ออกจากระบบ
        </button>
      </div>
    </div>
  )
}

function Layout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex h-screen">
      <Sidebar />
      <main className="flex-1 overflow-y-auto p-8">
        {children}
      </main>
    </div>
  )
}

// ─── Pages ────────────────────────────────────────────────────────────────────
function LoginPage() {
  const [email, setEmail] = useState('')
  const [name, setName] = useState('')
  const [isRegister, setIsRegister] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const { login } = useAuth()
  const navigate = useNavigate()

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setError('')
    setLoading(true)

    try {
      if (isRegister) {
        const { register } = await import('./lib/api')
        await register(email, name)
        alert('ลงทะเบียนสำเร็จ! กรุณารอ admin อนุมัติ')
        setIsRegister(false)
      } else {
        const { login: apiLogin, getMe } = await import('./lib/api')
        const { access_token } = await apiLogin(email)
        const user = await getMe(access_token)
        login(access_token, user)
        navigate('/chat')
      }
    } catch (err: any) {
      setError(err.message)
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="min-h-screen bg-dark-300 flex items-center justify-center p-4">
      <div className="w-full max-w-md">
        <div className="text-center mb-8">
          <h1 className="text-4xl font-bold text-primary-400 mb-2">⚖️ Legal GraphRAG</h1>
          <p className="text-slate-400">ระบบค้นหากฎหมายอัจฉริยะ — GraphRAG + Vector Search</p>
        </div>

        <div className="card">
          <h2 className="text-xl font-semibold mb-6">{isRegister ? 'ลงทะเบียน' : 'เข้าสู่ระบบ'}</h2>

          <form onSubmit={handleSubmit} className="space-y-4">
            {isRegister && (
              <div>
                <label className="block text-sm font-medium mb-1.5 text-slate-300">ชื่อ-นามสกุล</label>
                <input
                  type="text"
                  value={name}
                  onChange={e => setName(e.target.value)}
                  className="input"
                  placeholder="ชื่อของคุณ"
                  required
                />
              </div>
            )}

            <div>
              <label className="block text-sm font-medium mb-1.5 text-slate-300">อีเมล</label>
              <input
                type="email"
                value={email}
                onChange={e => setEmail(e.target.value)}
                className="input"
                placeholder="you@example.com"
                required
              />
            </div>

            {error && (
              <div className="p-3 bg-red-900/50 border border-red-700 rounded-lg text-red-300 text-sm">
                {error}
              </div>
            )}

            <button type="submit" disabled={loading} className="btn-primary w-full justify-center py-2.5">
              {loading ? 'กำลังโหลด...' : isRegister ? 'ลงทะเบียน' : 'เข้าสู่ระบบ'}
            </button>
          </form>

          <div className="mt-4 text-center">
            <button
              onClick={() => setIsRegister(!isRegister)}
              className="text-sm text-primary-400 hover:text-primary-300"
            >
              {isRegister ? 'มีบัญชีอยู่แล้ว? เข้าสู่ระบบ' : 'ยังไม่มีบัญชี? ลงทะเบียน'}
            </button>
          </div>
        </div>
      </div>
    </div>
  )
}

function ChatPage() {
  const [conversations, setConversations] = useState<any[]>([])
  const [activeConvId, setActiveConvId] = useState<string | null>(null)
  const [conversationsLoaded, setConversationsLoaded] = useState(false)
  const [question, setQuestion] = useState('')
  const [messages, setMessages] = useState<{ role: string; content: string }[]>([])
  const [loading, setLoading] = useState(false)
  const [latency, setLatency] = useState<number | null>(null)
  const { token } = useAuth()

  // Load conversation list on mount
  useEffect(() => {
    if (!token || conversationsLoaded) return
    import('./lib/api').then(({ listConversations }) => {
      listConversations(token).then(data => {
        setConversations(data.conversations || [])
        setConversationsLoaded(true)
      }).catch(() => setConversationsLoaded(true))
    })
  }, [token, conversationsLoaded])

  // Load messages when switching conversations
  const loadConversation = (convId: string) => {
    setActiveConvId(convId)
    setLoading(true)
    import('./lib/api').then(({ getConversationMessages }) => {
      getConversationMessages(convId, token!).then(data => {
        const msgs = (data.messages || []).map((m: any) => ({
          role: m.role === 'assistant' ? 'assistant' : m.role,
          content: m.content,
        }))
        setMessages(msgs)
        setLoading(false)
      }).catch(() => { setMessages([]); setLoading(false) })
    })
  }

  const startNewChat = async () => {
    setActiveConvId(null)
    setMessages([])
    if (!token) return
    try {
      const { createConversation } = await import('./lib/api')
      const data = await createConversation(token, {})
      if (data.id) {
        setConversations(prev => [{ id: data.id, title: data.title }, ...prev])
        setActiveConvId(data.id)
      }
    } catch {}
  }

  const handleAsk = async (e: React.FormEvent) => {
    e.preventDefault()
    if (!question.trim() || loading) return

    const userMsg = question
    setMessages(prev => [...prev, { role: 'user', content: userMsg }])
    setQuestion('')
    setLoading(true)

    // Build assistant placeholder
    const assistantId = Date.now()
    setMessages(prev => [...prev, { role: 'assistant', content: '' }])

    try {
      const { queryStream } = await import('./lib/api')
      await queryStream(
        userMsg,
        token!,
        activeConvId,
        (token: string) => {
          setMessages(prev => {
            const updated = [...prev]
            const last = updated[updated.length - 1]
            if (last && last.role === 'assistant') {
              updated[updated.length - 1] = { ...last, content: last.content + token }
            }
            return updated
          })
        },
        (done: boolean, lat: number, conv_id: string) => {
          if (done) {
            setLatency(lat)
            setLoading(false)
            if (!activeConvId && conv_id) {
              setActiveConvId(conv_id)
              setConversationsLoaded(false) // refresh list
            }
          }
        }
      )
    } catch (err: any) {
      setMessages(prev => {
        const updated = [...prev]
        const last = updated[updated.length - 1]
        if (last && last.role === 'assistant') last.content += `\n[Error: ${err.message}]`
        return updated
      })
      setLoading(false)
    }
  }

  return (
    <div className="flex gap-6 max-w-6xl mx-auto">
      {/* Conversation Sidebar */}
      <div className="w-56 flex-shrink-0">
        <button onClick={startNewChat} className="w-full btn-secondary mb-4 text-sm">
          + สนทนาใหม่
        </button>
        <div className="space-y-2">
          {conversations.map(c => (
            <button
              key={c.id}
              onClick={() => loadConversation(c.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs transition-colors ${
                activeConvId === c.id
                  ? 'bg-primary-600 text-white'
                  : 'bg-dark-100 text-slate-300 hover:bg-dark-200'
              }`}
            >
              <div className="truncate font-medium">{c.title || 'สนทนาใหม่'}</div>
              {c.updated_at && (
                <div className="text-slate-400 mt-0.5 text-[10px]">
                  {new Date(c.updated_at).toLocaleDateString('th-TH')}
                </div>
              )}
            </button>
          ))}
          {conversations.length === 0 && (
            <p className="text-xs text-slate-500 text-center py-4">ยังไม่มีสนทนา</p>
          )}
        </div>
      </div>

      {/* Chat Area */}
      <div className="flex-1 flex flex-col">
        <div className="mb-4">
          <h1 className="text-2xl font-bold">💬 ถาม-ตอบกฎหมาย</h1>
          <p className="text-slate-400 text-sm mt-1">
            {activeConvId ? 'สนทนา # ' + activeConvId.slice(0, 8) : 'สนทนาใหม่'}
            {latency && <span className="ml-3">⏱ {latency}ms</span>}
          </p>
        </div>

        <div className="card min-h-[400px] flex flex-col mb-4">
          <div className="flex-1 space-y-4 mb-4 overflow-y-auto">
            {messages.length === 0 && (
              <div className="text-center text-slate-500 py-12">
                <p className="text-4xl mb-3">⚖️</p>
                <p>เริ่มต้นถามคำถามกฎหมายได้เลย</p>
                <p className="text-sm mt-1">เช่น "พ.ร.บ. ข้อมูลข่าวสาร มาตรา 7 บอกอะไร?"</p>
              </div>
            )}

            {messages.map((msg, i) => (
              <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                <div className={`max-w-[80%] rounded-xl px-4 py-3 ${
                  msg.role === 'user' ? 'bg-primary-600 text-white' :
                  msg.role === 'error' ? 'bg-red-900/50 text-red-300 border border-red-700' :
                  'bg-dark-100 text-slate-100 border border-slate-600'
                }`}>
                  <p className="whitespace-pre-wrap text-sm">{msg.content}</p>
                  {msg.role === 'assistant' && i === messages.length - 1 && !loading && latency && (
                    <p className="text-xs text-slate-400 mt-1">⏱ {latency}ms</p>
                  )}
                </div>
              </div>
            ))}

            {loading && (
              <div className="flex justify-start">
                <div className="bg-dark-100 border border-slate-600 rounded-xl px-4 py-3">
                  <div className="flex gap-1">
                    <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" />
                    <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0.15s' }} />
                    <span className="w-2 h-2 bg-slate-400 rounded-full animate-bounce" style={{ animationDelay: '0.3s' }} />
                  </div>
                </div>
              </div>
            )}
          </div>

          <form onSubmit={handleAsk} className="flex gap-3">
            <input
              type="text"
              value={question}
              onChange={e => setQuestion(e.target.value)}
              placeholder="ถามคำถามกฎหมาย..."
              className="input flex-1"
              disabled={loading}
            />
            <button type="submit" disabled={loading || !question.trim()} className="btn-primary">
              ส่ง
            </button>
          </form>
        </div>
      </div>
    </div>
  )
}

function UsersPage() {
  const [tab, setTab] = useState<'pending' | 'all'>('pending')
  const [pending, setPending] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [roles, setRoles] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const { token, isAdmin } = useAuth()

  const load = async () => {
    setLoading(true)
    try {
      const { getPendingUsers, getUsers, getRoles } = await import('./lib/api')
      const [p, u, r] = await Promise.all([
        getPendingUsers(token!),
        tab === 'all' ? getUsers(token!) : Promise.resolve([]),
        getRoles(),
      ])
      setPending(p)
      setUsers(u)
      setRoles(r)
    } catch (err: any) {
      alert(err.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { if (token) load() }, [tab, token])

  const handleApprove = async (userId: string) => {
    try {
      const { approveUser } = await import('./lib/api')
      await approveUser(token!, userId)
      load()
    } catch (err: any) { alert(err.message) }
  }

  const handleReject = async (userId: string) => {
    const reason = prompt('เหตุผลที่ปฏิเสธ:')
    if (reason === null) return
    try {
      const { rejectUser } = await import('./lib/api')
      await rejectUser(token!, userId, reason)
      load()
    } catch (err: any) { alert(err.message) }
  }

  if (!isAdmin) return <Navigate to="/chat" replace />

  return (
    <div className="max-w-5xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">👥 จัดการผู้ใช้</h1>

      <div className="flex gap-4 mb-6">
        <button onClick={() => setTab('pending')} className={`px-4 py-2 rounded-lg font-medium ${tab === 'pending' ? 'bg-yellow-600 text-white' : 'btn-secondary'}`}>
          รออนุมัติ ({pending.length})
        </button>
        <button onClick={() => setTab('all')} className={`px-4 py-2 rounded-lg font-medium ${tab === 'all' ? 'bg-primary-600 text-white' : 'btn-secondary'}`}>
          ทั้งหมด
        </button>
      </div>

      {loading ? (
        <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
      ) : tab === 'pending' ? (
        <div className="space-y-3">
          {pending.length === 0 && <p className="text-slate-500">ไม่มีผู้ใช้รออนุมัติ</p>}
          {pending.map(u => (
            <div key={u.user_id} className="card flex items-center gap-4">
              <div className="w-10 h-10 bg-yellow-600 rounded-full flex items-center justify-center font-bold text-lg">
                {u.name.charAt(0)}
              </div>
              <div className="flex-1">
                <p className="font-medium">{u.name}</p>
                <p className="text-sm text-slate-400">{u.email}</p>
                <span className="badge badge-pending mt-1">ขอ role: {u.requested_role}</span>
              </div>
              <div className="flex gap-2">
                <button onClick={() => handleApprove(u.user_id)} className="btn-primary text-sm">✅ อนุมัติ</button>
                <button onClick={() => handleReject(u.user_id)} className="btn-danger text-sm">❌ ปฏิเสธ</button>
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-600 text-left">
                <th className="pb-3 font-medium text-slate-400">ผู้ใช้</th>
                <th className="pb-3 font-medium text-slate-400">Role</th>
                <th className="pb-3 font-medium text-slate-400">สถานะ</th>
                <th className="pb-3 font-medium text-slate-400">จัดการ</th>
              </tr>
            </thead>
            <tbody>
              {users.map(u => (
                <tr key={u.user_id} className="border-b border-slate-700/50">
                  <td className="py-3">
                    <p className="font-medium">{u.name}</p>
                    <p className="text-xs text-slate-400">{u.email}</p>
                  </td>
                  <td><span className="badge badge-system">{u.role_id}</span></td>
                  <td><span className={`badge badge-${u.status}`}>{u.status}</span></td>
                  <td>
                    <select
                      className="input py-1 text-xs w-auto"
                      value={u.role_id}
                      onChange={async (e) => {
                        try {
                          const { assignRole } = await import('./lib/api')
                          await assignRole(token!, u.user_id, e.target.value)
                          load()
                        } catch (err: any) { alert(err.message) }
                      }}
                    >
                      {roles.map(r => <option key={r.role_id} value={r.role_id}>{r.display_name}</option>)}
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function RolesPage() {
  const [roles, setRoles] = useState<any[]>([])
  const [perms, setPerms] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreate, setShowCreate] = useState(false)
  const { token, isAdmin } = useAuth()

  const load = async () => {
    setLoading(true)
    try {
      const { getRoles, getPermissions } = await import('./lib/api')
      const [r, p] = await Promise.all([getRoles(), getPermissions()])
      setRoles(r)
      setPerms(p)
    } catch (err: any) { alert(err.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  if (!isAdmin) return <Navigate to="/chat" replace />

  const groupedPerms = perms.reduce((acc: any, p: any) => {
    (acc[p.category] = acc[p.category] || []).push(p)
    return acc
  }, {})

  const handleDelete = async (roleId: string) => {
    if (!confirm('ลบ role นี้?')) return
    try {
      const { deleteRole } = await import('./lib/api')
      await deleteRole(token!, roleId)
      load()
    } catch (err: any) { alert(err.message) }
  }

  return (
    <div className="max-w-5xl mx-auto">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">🔐 จัดการสิทธิ์</h1>
          <p className="text-slate-400 text-sm mt-1">สร้างและแก้ไข roles + permissions</p>
        </div>
        <button onClick={() => setShowCreate(true)} className="btn-primary">+ สร้าง Role ใหม่</button>
      </div>

      {showCreate && (
        <CreateRoleModal
          perms={perms}
          onClose={() => setShowCreate(false)}
          onCreated={load}
          token={token!}
        />
      )}

      {loading ? (
        <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
      ) : (
        <div className="grid gap-4">
          {roles.map(role => (
            <div key={role.role_id} className="card">
              <div className="flex items-start justify-between mb-3">
                <div>
                  <div className="flex items-center gap-2">
                    <h3 className="font-semibold">{role.display_name}</h3>
                    {role.is_system && <span className="badge badge-system">System</span>}
                  </div>
                  <p className="text-sm text-slate-400">{role.description}</p>
                </div>
                {!role.is_system && (
                  <button onClick={() => handleDelete(role.role_id)} className="btn-danger text-xs py-1 px-2">ลบ</button>
                )}
              </div>
              <div className="flex flex-wrap gap-2">
                {role.permissions.map((p: string) => (
                  <span key={p} className="px-2 py-1 bg-dark-200 rounded text-xs text-slate-300">{p}</span>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

function CreateRoleModal({ perms, onClose, onCreated, token }: { perms: any[]; onClose: () => void; onCreated: () => void; token: string }) {
  const [name, setName] = useState('')
  const [displayName, setDisplayName] = useState('')
  const [desc, setDesc] = useState('')
  const [selected, setSelected] = useState<string[]>([])
  const [loading, setLoading] = useState(false)

  const toggle = (id: string) => {
    setSelected(prev => prev.includes(id) ? prev.filter(x => x !== id) : [...prev, id])
  }

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    setLoading(true)
    try {
      const { createRole } = await import('./lib/api')
      await createRole(token, { name, display_name: displayName, description: desc, permissions: selected })
      onCreated()
      onClose()
    } catch (err: any) { alert(err.message) }
    finally { setLoading(false) }
  }

  const grouped = perms.reduce((acc: any, p: any) => {
    (acc[p.category] = acc[p.category] || []).push(p)
    return acc
  }, {})

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-dark-100 rounded-xl border border-slate-600 w-full max-w-lg max-h-[80vh] overflow-y-auto">
        <div className="p-6 border-b border-slate-700 flex items-center justify-between">
          <h3 className="text-lg font-semibold">สร้าง Role ใหม่</h3>
          <button onClick={onClose} className="text-slate-400 hover:text-white text-xl">×</button>
        </div>
        <form onSubmit={handleSubmit} className="p-6 space-y-4">
          <div>
            <label className="block text-sm font-medium mb-1">ชื่อ (role_id)</label>
            <input value={name} onChange={e => setName(e.target.value)} className="input" placeholder="e.g. auditor" required />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">ชื่อที่แสดง</label>
            <input value={displayName} onChange={e => setDisplayName(e.target.value)} className="input" placeholder="ผู้ตรวจสอบ" required />
          </div>
          <div>
            <label className="block text-sm font-medium mb-1">คำอธิบาย</label>
            <input value={desc} onChange={e => setDesc(e.target.value)} className="input" placeholder="..." />
          </div>

          <div>
            <label className="block text-sm font-medium mb-2">Permissions</label>
            {Object.entries(grouped).map(([cat, items]: [string, any[]]) => (
              <div key={cat} className="mb-3">
                <p className="text-xs text-slate-400 uppercase mb-1">{cat}</p>
                <div className="flex flex-wrap gap-2">
                  {items.map((p: any) => (
                    <label key={p.permission_id} className="flex items-center gap-1.5 px-2 py-1 bg-dark-200 rounded cursor-pointer hover:bg-dark-300 text-xs">
                      <input
                        type="checkbox"
                        checked={selected.includes(p.permission_id)}
                        onChange={() => toggle(p.permission_id)}
                        className="accent-primary-500"
                      />
                      {p.name}
                    </label>
                  ))}
                </div>
              </div>
            ))}
          </div>

          <div className="flex gap-3 pt-2">
            <button type="submit" disabled={loading} className="btn-primary flex-1 justify-center">
              {loading ? 'กำลังสร้าง...' : 'สร้าง Role'}
            </button>
            <button type="button" onClick={onClose} className="btn-secondary flex-1">ยกเลิก</button>
          </div>
        </form>
      </div>
    </div>
  )
}

function StatsPage() {
  const [stats, setStats] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const { token, isAdmin } = useAuth()

  useEffect(() => {
    if (!token) return
    import('./lib/api').then(({ getStats }) => {
      getStats(token!).then(setStats).catch(() => {}).finally(() => setLoading(false))
    })
  }, [token])

  if (!isAdmin) return <Navigate to="/chat" replace />

  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">📊 สถิติระบบ</h1>
      {loading ? (
        <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
      ) : stats ? (
        <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
          {[
            { label: 'กฎหมาย', value: stats.stats.law, icon: '⚖️' },
            { label: 'มาตรา', value: stats.stats.section, icon: '📄' },
            { label: 'บทลงโทษ', value: stats.stats.penalty, icon: '🔨' },
            { label: 'ผู้ใช้', value: stats.stats.user, icon: '👥' },
            { label: 'Roles', value: stats.stats.role, icon: '🔐' },
            { label: 'รออนุมัติ', value: stats.stats.pending_users, icon: '⏳' },
          ].map(item => (
            <div key={item.label} className="card text-center">
              <p className="text-3xl mb-1">{item.icon}</p>
              <p className="text-3xl font-bold">{item.value ?? 0}</p>
              <p className="text-sm text-slate-400">{item.label}</p>
            </div>
          ))}
        </div>
      ) : (
        <div className="card text-center py-12 text-slate-400">
          ไม่สามารถโหลดสถิติได้
        </div>
      )}
    </div>
  )
}

function DocsPage() {
  return (
    <div className="max-w-4xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">📄 จัดการเอกสาร</h1>
      <div className="card text-center py-12 text-slate-400">
        <p className="text-4xl mb-3">📤</p>
        <p>ระบบอัพโหลดเอกสารกฎหมาย</p>
        <p className="text-sm mt-1">กำลังพัฒนา — รองรับ PDF จาก OCS ราชกิจจา</p>
      </div>
    </div>
  )
}

// ─── Protected Route ───────────────────────────────────────────────────────────
function RequireAuth({ children }: { children: React.ReactNode }) {
  const { token } = useAuth()
  return token ? <>{children}</> : <Navigate to="/login" replace />
}

// ─── App ──────────────────────────────────────────────────────────────────────
export default function App() {
  const [user, setUser] = useState<User | null>(null)
  const [token, setToken] = useState<string | null>(null)

  const login = (t: string, u: User) => {
    setToken(t)
    setUser(u)
    localStorage.setItem('lg_token', t)
    localStorage.setItem('lg_user', JSON.stringify(u))
  }

  const logout = () => {
    setToken(null)
    setUser(null)
    localStorage.removeItem('lg_token')
    localStorage.removeItem('lg_user')
  }

  // Restore session
  useEffect(() => {
    const savedToken = localStorage.getItem('lg_token')
    const savedUser = localStorage.getItem('lg_user')
    if (savedToken && savedUser) {
      setToken(savedToken)
      setUser(JSON.parse(savedUser))
    }
  }, [])

  return (
    <AuthContext.Provider value={{ user, token, login, logout, isAdmin: user?.role_id === 'admin' }}>
      <BrowserRouter>
        <Routes>
          <Route path="/login" element={token ? <Navigate to="/chat" /> : <LoginPage />} />
          <Route path="/" element={<RequireAuth><Layout /></RequireAuth>}>
            <Route index element={<Navigate to="/chat" />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="request-api-key" element={<RequestApiKeyPage />} />
            <Route path="my-api-keys" element={<MyApiKeysPage />} />
            <Route path="my-doc-access" element={<MyDocAccessPage />} />
            <Route path="users" element={<UsersPage />} />
            <Route path="roles" element={<RolesPage />} />
            <Route path="docs" element={<DocsPage />} />
            <Route path="stats" element={<StatsPage />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AuthContext.Provider>
  )
}
