import { useState } from 'react'

const API = '/api/v1'

function getToken() { return localStorage.getItem('lg_token') || '' }

interface Collection {
  name: string
  points_count: number
  vectors_count: number
  status: string
}

interface PointPreview {
  id: string
  score: number
  payload: Record<string, any>
}

export default function VectorStorePage() {
  const [collections, setCollections] = useState<Collection[]>([])
  const [selected, setSelected] = useState<string>('')
  const [points, setPoints] = useState<PointPreview[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  async function fetchCollections() {
    setLoading(true)
    try {
      const r = await fetch(`${API}/admin/qdrant/collections`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      })
      if (r.ok) {
        const data = await r.json()
        setCollections(data)
        if (data.length > 0 && !selected) setSelected(data[0].name)
      } else setError(`Error ${r.status}`)
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  async function fetchPoints(collection: string) {
    setLoading(true)
    try {
      const r = await fetch(`${API}/admin/qdrant/collections/${collection}/points?limit=20`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      })
      if (r.ok) setPoints(await r.json())
      else setError(`Error ${r.status}`)
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  async function deleteCollection(name: string) {
    if (!confirm(`ลบ collection "${name}" ?`)) return
    const r = await fetch(`${API}/admin/qdrant/collections/${name}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${getToken()}` }
    })
    if (r.ok) { setCollections(collections.filter(c => c.name !== name)); setSelected('') }
  }

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">🔢 Vector Store (Qdrant)</h1>

      <div className="flex gap-4">
        {/* Collections sidebar */}
        <div className="w-64 shrink-0">
          <div className="flex justify-between items-center mb-3">
            <h2 className="font-semibold">Collections</h2>
            <button onClick={fetchCollections} disabled={loading}
              className="btn btn-xs btn-outline">🔄</button>
          </div>
          <div className="space-y-2">
            {collections.map(c => (
              <div key={c.name}
                className={`card p-3 cursor-pointer ${selected === c.name ? 'border-primary' : ''}`}
                onClick={() => { setSelected(c.name); fetchPoints(c.name) }}>
                <p className="font-mono text-sm text-primary truncate">{c.name}</p>
                <p className="text-xs text-slate-400">{c.points_count.toLocaleString()} points</p>
                <p className="text-xs text-slate-500">{c.status}</p>
              </div>
            ))}
            {collections.length === 0 && (
              <button onClick={fetchCollections} className="btn btn-outline btn-sm w-full">
                📡 Load Collections
              </button>
            )}
          </div>
        </div>

        {/* Points detail */}
        <div className="flex-1">
          {selected ? (
            <>
              <div className="flex justify-between items-center mb-3">
                <h2 className="font-semibold">Points in <span className="text-primary">{selected}</span></h2>
                <button onClick={() => fetchPoints(selected)} disabled={loading}
                  className="btn btn-xs btn-outline">🔄 Refresh</button>
              </div>
              {loading ? (
                <p className="text-slate-400">กำลังโหลด...</p>
              ) : points.length === 0 ? (
                <div className="card p-8 text-center text-slate-400">
                  <p>ยังไม่มี points — อัพโหลดเอกสารก่อน</p>
                </div>
              ) : (
                <div className="space-y-3">
                  {points.map((p, i) => (
                    <div key={i} className="card p-4">
                      <div className="flex justify-between mb-1">
                        <span className="font-mono text-xs text-slate-500">ID: {p.id}</span>
                        <span className="text-xs text-slate-400">score: {p.score?.toFixed(4)}</span>
                      </div>
                      <pre className="text-xs text-slate-300 whitespace-pre-wrap overflow-hidden max-h-32">
                        {JSON.stringify(p.payload, null, 2)}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </>
          ) : (
            <div className="card p-8 text-center text-slate-400">
              <p>เลือก collection ด้านซ้าย</p>
            </div>
          )}
        </div>
      </div>
    </div>
  )
}
