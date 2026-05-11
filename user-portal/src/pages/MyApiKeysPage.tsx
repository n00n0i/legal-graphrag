import { useState, useEffect } from 'react'

export default function MyApiKeysPage() {
  const [keys, setKeys] = useState<any[]>([])
  const [requests, setRequests] = useState<any[]>([])
  const [tab, setTab] = useState<'keys'|'requests'>('keys')
  const [loading, setLoading] = useState(true)
  const token = localStorage.getItem('lgu_token')

  const load = async () => {
    setLoading(true)
    try {
      const [kRes, rRes] = await Promise.all([
        fetch('/api/v1/user/api-key/my-keys', { headers: { Authorization: `Bearer ${token}` } }),
        fetch('/api/v1/user/api-key/my-requests', { headers: { Authorization: `Bearer ${token}` } }),
      ])
      const [k, r] = await Promise.all([kRes.json(), rRes.json()])
      setKeys(Array.isArray(k) ? k : [])
      setRequests(Array.isArray(r) ? r : [])
    } catch (e: any) { alert(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load() }, [])

  return (
    <div className="min-h-screen bg-dark-300 p-8">
      <div className="max-w-4xl mx-auto">
        <div className="flex items-center justify-between mb-6">
          <div>
            <h1 className="text-2xl font-bold">🔑 My API Keys</h1>
            <p className="text-slate-400 text-sm mt-1">Manage your API keys</p>
          </div>
          <button onClick={load} className="btn-secondary text-sm">🔄 Refresh</button>
        </div>

        <div className="flex gap-2 mb-6">
          <button onClick={() => setTab('keys')}
            className={`px-4 py-2 rounded-lg font-medium ${tab === 'keys' ? 'bg-primary-600 text-white' : 'btn-secondary'}`}>
            My Keys ({keys.length})
          </button>
          <button onClick={() => setTab('requests')}
            className={`px-4 py-2 rounded-lg font-medium ${tab === 'requests' ? 'bg-primary-600 text-white' : 'btn-secondary'}`}>
            My Requests ({requests.length})
          </button>
        </div>

        {loading ? <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
        : tab === 'keys' ? (
          keys.length === 0 ? (
            <div className="card text-center py-16 text-slate-400">
              <p className="text-4xl mb-3">🔑</p>
              <p>No API keys yet</p>
              <p className="text-sm mt-1">Request one from the settings</p>
            </div>
          ) : (
            <div className="space-y-3">
              {keys.map(k => (
                <div key={k.key_id} className="card">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-mono text-primary-400 font-bold text-lg">{k.key_prefix}••••••••</p>
                      <div className="flex gap-2 mt-2">
                        <span className={`badge ${k.tier==='enterprise'?'badge-accent':k.tier==='premium'?'badge-primary':k.tier==='standard'?'badge-active':'badge-pending'}`}>{k.tier}</span>
                        <span className={`badge ${k.is_active?'badge-active':'badge-danger'}`}>{k.is_active?'Active':'Revoked'}</span>
                      </div>
                    </div>
                    <div className="text-right text-sm text-slate-400">
                      <p>Rate: {k.rate_limit_rpm} req/min</p>
                      <p>Created: {k.created_at ? new Date(k.created_at).toLocaleDateString('th-TH') : '-'}</p>
                      {k.expires_at && <p>Expires: {new Date(k.expires_at).toLocaleDateString('th-TH')}</p>}
                    </div>
                  </div>
                  {!k.is_active && <p className="text-red-400 text-sm mt-2">⚠️ This key has been revoked</p>}
                  <div className="mt-3 bg-dark-200 rounded-lg p-3 text-xs text-slate-400">
                    ⚠️ The raw key is only shown once at approval time. Use the prefix above to identify it.
                  </div>
                </div>
              ))}
            </div>
          )
        ) : (
          requests.length === 0 ? (
            <div className="card text-center py-16 text-slate-400">
              <p className="text-4xl mb-3">📭</p>
              <p>No requests yet</p>
            </div>
          ) : (
            <div className="space-y-3">
              {requests.map(r => (
                <div key={r.request_id} className="card">
                  <div className="flex items-center justify-between">
                    <div>
                      <p className="font-medium">{r.purpose}</p>
                      <p className="text-sm text-slate-400 mt-1">Requested: {new Date(r.created_at).toLocaleString('th-TH')}</p>
                    </div>
                    <span className={`badge ${r.status === 'pending' ? 'badge-pending' : r.status === 'approved' ? 'badge-active' : 'badge-danger'}`}>{r.status}</span>
                  </div>
                </div>
              ))}
            </div>
          )
        )}
      </div>
    </div>
  )
}
