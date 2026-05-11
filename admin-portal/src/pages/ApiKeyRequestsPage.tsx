import { useState, useEffect } from 'react'

export default function ApiKeyRequestsPage() {
  const [requests, setRequests] = useState<any[]>([])
  const [status, setStatus] = useState<string>('')
  const [loading, setLoading] = useState(true)

  const load = async (s?: string) => {
    setLoading(true)
    try {
      const token = localStorage.getItem('lga_token')
      const url = s ? `/api/v1/admin/api-key/requests?status=${s}` : '/api/v1/admin/api-key/requests'
      const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } })
      const data = await res.json()
      setRequests(Array.isArray(data) ? data : [])
    } catch (e: any) { alert(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { load(status || undefined) }, [status])

  const approve = async (requestId: string) => {
    try {
      const token = localStorage.getItem('lga_token')
      const res = await fetch(`/api/v1/admin/api-key/approve/${requestId}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/x-www-form-urlencoded' }
      })
      const data = await res.json()
      if (!res.ok) throw new Error(data.detail || 'Failed')
      // Show the raw API key ONCE
      alert(`✅ API Key Approved!

Your API Key: ${data.raw_api_key}

⚠️ Copy this now — it will not be shown again!

Prefix: ${data.key_prefix}
Tier: ${data.tier}
Rate: ${data.rate_limit_rpm} req/min`)
      load(status || undefined)
    } catch (e: any) { alert(e.message) }
  }

  const reject = async (requestId: string) => {
    const reason = prompt('Rejection reason:')
    if (reason === null) return
    try {
      const token = localStorage.getItem('lga_token')
      await fetch(`/api/v1/admin/api-key/reject/${requestId}?reason=${encodeURIComponent(reason)}`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/x-www-form-urlencoded' }
      })
      load(status || undefined)
    } catch (e: any) { alert(e.message) }
  }

  return (
    <div className="max-w-5xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">📨 API Key Requests</h1>
          <p className="text-slate-400 text-sm mt-1">Approve or reject API key requests from users</p>
        </div>
        <div className="flex gap-2">
          <select value={status} onChange={e => setStatus(e.target.value)} className="input py-1.5 text-sm w-36">
            <option value="">All</option>
            <option value="pending">Pending</option>
            <option value="approved">Approved</option>
            <option value="rejected">Rejected</option>
          </select>
          <button onClick={() => load(status || undefined)} className="btn-secondary text-sm">🔄 Refresh</button>
        </div>
      </div>

      {loading ? <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
      : requests.length === 0 ? (
        <div className="card text-center py-16 text-slate-400">
          <p className="text-4xl mb-3">📭</p>
          <p>ไม่มีคำขอ API key</p>
        </div>
      ) : (
        <div className="space-y-3">
          {requests.map(r => (
            <div key={r.request_id} className="card">
              <div className="flex items-start justify-between">
                <div className="flex gap-4">
                  <div className="w-10 h-10 bg-dark-200 rounded-full flex items-center justify-center font-bold">
                    {r.name?.charAt(0) || '?'}
                  </div>
                  <div>
                    <p className="font-semibold">{r.name}</p>
                    <p className="text-sm text-slate-400">{r.email}</p>
                    <p className="text-xs text-slate-500 mt-1">ID: {r.user_id}</p>
                  </div>
                </div>
                <div className="flex flex-col items-end gap-1">
                  <span className={`badge ${
                    r.status === 'pending' ? 'badge-pending' :
                    r.status === 'approved' ? 'badge-active' : 'badge-danger'
                  }`}>{r.status}</span>
                  <span className="badge badge-system">{r.tier}</span>
                </div>
              </div>
              <div className="mt-3 p-3 bg-dark-200 rounded-lg">
                <p className="text-xs text-slate-400 mb-1">Purpose</p>
                <p className="text-sm">{r.purpose}</p>
              </div>
              <div className="flex items-center justify-between mt-3">
                <p className="text-xs text-slate-500">Requested: {new Date(r.created_at).toLocaleString('th-TH')}</p>
                {r.status === 'pending' && (
                  <div className="flex gap-2">
                    <button onClick={() => approve(r.request_id)} className="btn-success text-sm px-4 py-1.5">✅ Approve</button>
                    <button onClick={() => reject(r.request_id)} className="btn-danger text-sm px-4 py-1.5">❌ Reject</button>
                  </div>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
