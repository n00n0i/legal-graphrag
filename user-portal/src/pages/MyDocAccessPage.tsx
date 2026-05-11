import { useState, useEffect } from 'react'

export default function MyDocAccessPage() {
  const [access, setAccess] = useState<any[]>([])
  const [loading, setLoading] = useState(true)
  const token = localStorage.getItem('lgu_token')

  useEffect(() => {
    const load = async () => {
      setLoading(true)
      try {
        const res = await fetch('/api/v1/user/doc-access/my-access', { headers: { Authorization: `Bearer ${token}` } })
        const data = await res.json()
        setAccess(Array.isArray(data) ? data : [])
      } catch (e: any) { alert(e.message) }
      finally { setLoading(false) }
    }
    load()
  }, [])

  return (
    <div className="min-h-screen bg-dark-300 p-8">
      <div className="max-w-4xl mx-auto">
        <h1 className="text-2xl font-bold mb-6">📋 My Document Access</h1>

        {loading ? <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
        : access.length === 0 ? (
          <div className="card text-center py-16 text-slate-400">
            <p className="text-4xl mb-3">📋</p>
            <p>No document access granted yet</p>
            <p className="text-sm mt-1">Contact admin to get access to documents</p>
          </div>
        ) : (
          <div className="card overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-600 text-left">
                  <th className="pb-3 font-medium text-slate-400">Document</th>
                  <th className="pb-3 font-medium text-slate-400">Access Level</th>
                  <th className="pb-3 font-medium text-slate-400">Granted By</th>
                  <th className="pb-3 font-medium text-slate-400">Granted At</th>
                  <th className="pb-3 font-medium text-slate-400">Expires</th>
                </tr>
              </thead>
              <tbody>
                {access.map(a => (
                  <tr key={a.permission_id} className="border-b border-slate-700/50">
                    <td className="py-3">
                      <p className="font-medium">{a.doc_title}</p>
                      <p className="text-xs text-slate-500">{a.doc_id}</p>
                    </td>
                    <td className="py-3">
                      <span className={`badge ${a.access_level==='admin'?'badge-accent':a.access_level==='write'?'badge-primary':'badge-system'}`}>{a.access_level}</span>
                    </td>
                    <td className="py-3 text-slate-400 text-xs">{a.granted_by}</td>
                    <td className="py-3 text-slate-400 text-xs">{a.granted_at ? new Date(a.granted_at).toLocaleDateString('th-TH') : '-'}</td>
                    <td className="py-3 text-slate-400 text-xs">{a.expires_at ? new Date(a.expires_at).toLocaleDateString('th-TH') : 'Never'}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}
