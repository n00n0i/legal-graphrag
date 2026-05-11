import { useState, useEffect } from 'react'

export default function DocAccessPage() {
  const [accessList, setAccessList] = useState<any[]>([])
  const [users, setUsers] = useState<any[]>([])
  const [docs, setDocs] = useState<any[]>([])
  const [filterUid, setFilterUid] = useState('')
  const [filterDoc, setFilterDoc] = useState('')
  const [loading, setLoading] = useState(true)
  const [showGrant, setShowGrant] = useState(false)

  // Grant form
  const [grantUser, setGrantUser] = useState('')
  const [grantDoc, setGrantDoc] = useState('')
  const [grantLevel, setGrantLevel] = useState('read')
  const [grantExpiry, setGrantExpiry] = useState('')

  const token = localStorage.getItem('lga_token')

  const load = async () => {
    setLoading(true)
    try {
      const params = new URLSearchParams()
      if (filterUid) params.append('user_id', filterUid)
      if (filterDoc) params.append('doc_id', filterDoc)
      const url = '/api/v1/admin/doc-access/list?' + params.toString()
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setAccessList(Array.isArray(data) ? data : [])
    } catch (e: any) { alert(e.message) }
    finally { setLoading(false) }
  }

  const loadUsers = async () => {
    try {
      const res = await fetch('/api/v1/admin/users?limit=100', { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setUsers(Array.isArray(data) ? data.filter((u: any) => u.status === 'active') : [])
    } catch (e: any) {}
  }

  const loadDocs = async () => {
    try {
      const res = await fetch('/api/v1/admin/documents?limit=100', { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setDocs(Array.isArray(data) ? data : [])
    } catch (e: any) {}
  }

  useEffect(() => { load(); loadUsers(); loadDocs() }, [])

  const grant = async () => {
    if (!grantUser || !grantDoc) { alert('Select user and document'); return }
    try {
      const body = new URLSearchParams()
      body.append('user_id', grantUser)
      body.append('doc_id', grantDoc)
      body.append('access_level', grantLevel)
      if (grantExpiry) body.append('expires_at', new Date(grantExpiry).toISOString())

      const res = await fetch('/api/v1/admin/doc-access/grant', {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/x-www-form-urlencoded' },
        body
      })
      if (!res.ok) throw new Error((await res.json()).detail)
      setShowGrant(false)
      setGrantUser(''); setGrantDoc(''); setGrantLevel('read'); setGrantExpiry('')
      load()
    } catch (e: any) { alert(e.message) }
  }

  const revoke = async (permId: string) => {
    if (!confirm('Revoke this document access?')) return
    try {
      await fetch(`/api/v1/admin/doc-access/revoke/${permId}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` }
      })
      load()
    } catch (e: any) { alert(e.message) }
  }

  return (
    <div className="max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">📋 Document Access</h1>
          <p className="text-slate-400 text-sm mt-1">Grant or revoke per-user document access</p>
        </div>
        <div className="flex gap-2">
          <input placeholder="User ID" value={filterUid} onChange={e => setFilterUid(e.target.value)} className="input py-1.5 text-sm w-36" />
          <input placeholder="Doc ID" value={filterDoc} onChange={e => setFilterDoc(e.target.value)} className="input py-1.5 text-sm w-36" />
          <button onClick={() => load()} className="btn-secondary text-sm">🔍 Filter</button>
          <button onClick={() => { setFilterUid(''); setFilterDoc(''); load() }} className="btn-secondary text-sm">Clear</button>
          <button onClick={() => { setShowGrant(true); loadUsers(); loadDocs() }} className="btn-accent text-sm">+ Grant Access</button>
          <button onClick={load} className="btn-secondary text-sm">🔄 Refresh</button>
        </div>
      </div>

      {/* Grant Modal */}
      {showGrant && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
          <div className="bg-dark-100 rounded-xl border border-slate-600 w-full max-w-md p-6">
            <h3 className="text-lg font-semibold mb-4">Grant Document Access</h3>
            <div className="space-y-4">
              <div>
                <label className="block text-sm font-medium mb-1">User</label>
                <select value={grantUser} onChange={e => setGrantUser(e.target.value)} className="input w-full">
                  <option value="">Select user...</option>
                  {users.map(u => <option key={u.user_id} value={u.user_id}>{u.name} ({u.email})</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Document</label>
                <select value={grantDoc} onChange={e => setGrantDoc(e.target.value)} className="input w-full">
                  <option value="">Select document...</option>
                  {docs.map(d => <option key={d.doc_id} value={d.doc_id}>{d.title || d.doc_id}</option>)}
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Access Level</label>
                <select value={grantLevel} onChange={e => setGrantLevel(e.target.value)} className="input w-full">
                  <option value="read">Read</option>
                  <option value="write">Write</option>
                  <option value="admin">Admin (full control)</option>
                </select>
              </div>
              <div>
                <label className="block text-sm font-medium mb-1">Expires (optional)</label>
                <input type="datetime-local" value={grantExpiry} onChange={e => setGrantExpiry(e.target.value)} className="input w-full" />
              </div>
              <div className="flex gap-3 pt-2">
                <button onClick={grant} className="btn-accent flex-1 justify-center">Grant</button>
                <button onClick={() => setShowGrant(false)} className="btn-secondary flex-1">Cancel</button>
              </div>
            </div>
          </div>
        </div>
      )}

      {loading ? <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
      : accessList.length === 0 ? (
        <div className="card text-center py-16 text-slate-400">
          <p className="text-4xl mb-3">📋</p>
          <p>ยังไม่มี document access permissions</p>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-600 text-left">
                <th className="pb-3 font-medium text-slate-400">User</th>
                <th className="pb-3 font-medium text-slate-400">Document</th>
                <th className="pb-3 font-medium text-slate-400">Level</th>
                <th className="pb-3 font-medium text-slate-400">Granted By</th>
                <th className="pb-3 font-medium text-slate-400">Granted At</th>
                <th className="pb-3 font-medium text-slate-400">Expires</th>
                <th className="pb-3 font-medium text-slate-400">Status</th>
                <th className="pb-3 font-medium text-slate-400">Revoke</th>
              </tr>
            </thead>
            <tbody>
              {accessList.map(a => (
                <tr key={a.permission_id} className="border-b border-slate-700/50">
                  <td className="py-3">
                    <p className="font-medium text-xs">{a.user_id}</p>
                    <p className="text-xs text-slate-400">{a.email}</p>
                  </td>
                  <td className="py-3">
                    <p className="font-medium text-xs max-w-[200px] truncate">{a.doc_title}</p>
                    <p className="text-xs text-slate-500">{a.doc_id}</p>
                  </td>
                  <td className="py-3">
                    <span className={`badge ${a.access_level==='admin'?'badge-accent':a.access_level==='write'?'badge-primary':'badge-system'}`}>{a.access_level}</span>
                  </td>
                  <td className="py-3 text-xs text-slate-400">{a.granted_by}</td>
                  <td className="py-3 text-xs text-slate-400">{a.granted_at ? new Date(a.granted_at).toLocaleDateString('th-TH') : '-'}</td>
                  <td className="py-3 text-xs text-slate-400">{a.expires_at ? new Date(a.expires_at).toLocaleDateString('th-TH') : 'Never'}</td>
                  <td className="py-3"><span className={`badge ${a.is_revoked?'badge-danger':'badge-active'}`}>{a.is_revoked?'Revoked':'Active'}</span></td>
                  <td className="py-3">
                    {!a.is_revoked && <button onClick={() => revoke(a.permission_id)} className="btn-danger text-xs px-2 py-1">✕</button>}
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
