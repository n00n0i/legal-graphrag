import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'

export default function ApiKeysPage() {
  const [keys, setKeys] = useState<any[]>([])
  const [filterUid, setFilterUid] = useState('')
  const [loading, setLoading] = useState(true)

  const load = async (uid?: string) => {
    setLoading(true)
    try {
      const token = localStorage.getItem('lga_token')
      const url = uid ? `/api/v1/admin/api-keys?user_id=${uid}` : '/api/v1/admin/api-keys'
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setKeys(Array.isArray(data) ? data : [])
    } catch (e: any) { alert(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  const revoke = async (keyId: string) => {
    if (!confirm('Revoke this API key?')) return
    try {
      const token = localStorage.getItem('lga_token')
      await fetch(`/api/v1/admin/api-key/revoke/${keyId}?reason=admin_revoked`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/x-www-form-urlencoded' }
      })
      load(filterUid || undefined)
    } catch (e: any) { alert(e.message) }
  }

  return (
    <div className="max-w-7xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">🔑 API Keys</h1>
          <p className="text-slate-400 text-sm mt-1">Issued API keys — revoke any key from here</p>
        </div>
        <div className="flex gap-2">
          <input
            placeholder="Filter by user_id..."
            value={filterUid}
            onChange={e => setFilterUid(e.target.value)}
            className="input py-1.5 text-sm w-48"
          />
          <button onClick={() => load(filterUid || undefined)} className="btn-secondary text-sm">🔍 Filter</button>
          <button onClick={() => { setFilterUid(''); load() }} className="btn-secondary text-sm">Clear</button>
          <button onClick={load} className="btn-secondary text-sm">🔄 Refresh</button>
        </div>
      </div>

      {loading ? <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
      : keys.length === 0 ? (
        <div className="card text-center py-16 text-slate-400">
          <p className="text-4xl mb-3">🔑</p>
          <p>ยังไม่มี API key ที่ออกให้</p>
        </div>
      ) : (
        <div className="card overflow-x-auto">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-slate-600 text-left">
                <th className="pb-3 font-medium text-slate-400">Key Prefix</th>
                <th className="pb-3 font-medium text-slate-400">User</th>
                <th className="pb-3 font-medium text-slate-400">Tier</th>
                <th className="pb-3 font-medium text-slate-400">RPM</th>
                <th className="pb-3 font-medium text-slate-400">Status</th>
                <th className="pb-3 font-medium text-slate-400">Created</th>
                <th className="pb-3 font-medium text-slate-400">Last Used</th>
                <th className="pb-3 font-medium text-slate-400">Expires</th>
                <th className="pb-3 font-medium text-slate-400">Revoke</th>
              </tr>
            </thead>
            <tbody>
              {keys.map(k => (
                <tr key={k.key_id} className="border-b border-slate-700/50">
                  <td className="py-3 font-mono text-primary-400 font-bold">{k.key_prefix}</td>
                  <td className="py-3">
                    <p className="font-medium text-xs">{k.user_id}</p>
                    <p className="text-xs text-slate-400">{k.email}</p>
                  </td>
                  <td className="py-3"><span className={`badge ${k.tier==='enterprise'?'badge-accent':k.tier==='premium'?'badge-primary':k.tier==='standard'?'badge-active':'badge-pending'}`}>{k.tier}</span></td>
                  <td className="py-3 text-slate-300">{k.rate_limit_rpm}</td>
                  <td className="py-3"><span className={`badge ${k.is_active?'badge-active':'badge-danger'}`}>{k.is_active?'Active':'Revoked'}</span></td>
                  <td className="py-3 text-slate-400 text-xs">{k.created_at ? new Date(k.created_at).toLocaleDateString('th-TH') : '-'}</td>
                  <td className="py-3 text-slate-400 text-xs">{k.last_used_at ? new Date(k.last_used_at).toLocaleDateString('th-TH') : 'Never'}</td>
                  <td className="py-3 text-slate-400 text-xs">{k.expires_at ? new Date(k.expires_at).toLocaleDateString('th-TH') : 'Never'}</td>
                  <td className="py-3">
                    <button onClick={() => revoke(k.key_id)} className="btn-danger text-xs px-2 py-1">✕ Revoke</button>
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
