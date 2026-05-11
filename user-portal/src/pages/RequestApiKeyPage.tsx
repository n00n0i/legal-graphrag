import { useState } from 'react'
import { useNavigate } from 'react-router-dom'

export default function RequestApiKeyPage() {
  const [purpose, setPurpose] = useState('')
  const [tier, setTier] = useState('free')
  const [loading, setLoading] = useState(false)
  const navigate = useNavigate()
  const token = localStorage.getItem('lgu_token')

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault()
    if (purpose.length < 10) { alert('Purpose must be at least 10 characters'); return }
    setLoading(true)
    try {
      const res = await fetch('/api/v1/user/api-key/request', {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${token}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ purpose, tier })
      })
      if (!res.ok) throw new Error((await res.json()).detail || 'Request failed')
      alert('✅ API key request submitted! Awaiting admin approval.')
      navigate('/my-api-keys')
    } catch (e: any) { alert(e.message) }
    finally { setLoading(false) }
  }

  return (
    <div className="min-h-screen bg-dark-300 flex items-center justify-center p-4">
      <div className="w-full max-w-xl">
        <div className="text-center mb-8">
          <h1 className="text-3xl font-bold text-primary-400 mb-2">🔑 Request API Key</h1>
          <p className="text-slate-400">Get a key to use Legal GraphRAG as a service programmatically</p>
        </div>
        <div className="card p-8">
          <h2 className="font-semibold mb-4">API Key Request</h2>
          <form onSubmit={handleSubmit} className="space-y-5">
            <div>
              <label className="block text-sm font-medium mb-1.5 text-slate-300">Purpose *</label>
              <textarea
                value={purpose}
                onChange={e => setPurpose(e.target.value)}
                className="input w-full h-28"
                placeholder="Describe how you plan to use the API... (min 10 characters)"
                required
                minLength={10}
              />
            </div>
            <div>
              <label className="block text-sm font-medium mb-1.5 text-slate-300">Tier</label>
              <select value={tier} onChange={e => setTier(e.target.value)} className="input w-full">
                <option value="free">Free — 10 req/min, 500/day</option>
                <option value="standard">Standard — 60 req/min, 5K/day</option>
                <option value="premium">Premium — 300 req/min, 50K/day</option>
                <option value="enterprise">Enterprise — 1000 req/min, unlimited</option>
              </select>
            </div>
            <div className="bg-dark-200 rounded-lg p-4 text-sm">
              <p className="text-slate-400 mb-2">What happens next:</p>
              <ol className="list-decimal list-inside space-y-1 text-slate-300">
                <li>Submit request → admin reviews</li>
                <li>Admin approves → you get your raw API key (shown only once!)</li>
                <li>Use the key: <code className="text-primary-400">Authorization: Bearer YOUR_API_KEY</code></li>
              </ol>
            </div>
            {loading ? (
              <div className="text-center py-3 text-slate-400">Submitting...</div>
            ) : (
              <button type="submit" className="btn-accent w-full justify-center py-2.5">
                Submit Request
              </button>
            )}
          </form>
        </div>
      </div>
    </div>
  )
}
