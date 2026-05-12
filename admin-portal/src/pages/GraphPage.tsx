import { useState } from 'react'

const API = '/api/v1'

function getToken() { return localStorage.getItem('lg_token') || '' }

interface Stats {
  total_nodes: number
  total_relationships: number
  labels: { label: string; count: number }[]
}

interface NodeResult {
  id: string
  labels: string[]
  props: Record<string, any>
}

interface RelResult {
  type: string
  count: number
  startLabel: string
  endLabel: string
}

export default function GraphPage() {
  const [stats, setStats] = useState<Stats | null>(null)
  const [query, setQuery] = useState('MATCH (n) RETURN labels(n) as labels, count(n) as count, head(collect(properties(n))) as sample LIMIT 20')
  const [customQuery, setCustomQuery] = useState('')
  const [queryResult, setQueryResult] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [tab, setTab] = useState<'stats' | 'nodes' | 'cypher'>('stats')

  async function fetchStats() {
    setLoading(true)
    try {
      const r = await fetch(`${API}/admin/neo4j/stats`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      })
      if (r.ok) setStats(await r.json())
      else setError(`Error ${r.status}`)
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  async function runCypher() {
    if (!customQuery.trim()) return
    setLoading(true)
    setError('')
    try {
      const r = await fetch(`${API}/admin/neo4j/cypher`, {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${getToken()}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({ query: customQuery }),
      })
      if (r.ok) {
        const data = await r.json()
        setQueryResult(JSON.stringify(data, null, 2))
      } else {
        const err = await r.json()
        setError(err.detail || `Error ${r.status}`)
      }
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  const presets = [
    { label: '📊 Stats ทั้งหมด', query: 'MATCH (n) RETURN labels(n) as labels, count(n) as count ORDER BY count DESC LIMIT 20' },
    { label: '📜 Laws', query: "MATCH (l:Law) RETURN l.title as title, l.law_type as type, l.total_chunks as chunks ORDER BY l.uploaded_at DESC LIMIT 50" },
    { label: '⚖️ Sections', query: 'MATCH (s:Section) RETURN s.number as number, s.content as content, count(s) as count LIMIT 30' },
    { label: '👥 Users', query: 'MATCH (u:User) RETURN u.email as email, u.name as name, u.status as status LIMIT 50' },
    { label: '🔑 API Keys', query: 'MATCH (u:User)-[:HAS_API_KEY]->(k:ApiKey) RETURN u.email as user, k.tier as tier, k.is_active as active, k.created_at as created LIMIT 50' },
    { label: '📄 Doc Access', query: 'MATCH (u:User)-[:HAS_ACCESS]->(d:DocAccess) RETURN u.email as user, d.law_id as doc, d.access_level as level, d.granted_at as granted LIMIT 50' },
    { label: '🔗 Relationships', query: 'CALL db.relationshipTypes() YIELD relationshipType RETURN relationshipType, count(*) as count ORDER BY count DESC' },
  ]

  return (
    <div className="max-w-7xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">🕸️ Graph Browser (Neo4j)</h1>

      {/* Tabs */}
      <div className="flex gap-2 mb-6">
        {(['stats', 'nodes', 'cypher'] as const).map(t => (
          <button key={t} onClick={() => { setTab(t); if (t === 'stats') fetchStats() }}
            className={`btn btn-sm ${tab === t ? 'btn-primary' : 'btn-outline'}`}>
            {t === 'stats' ? '📊 Stats' : t === 'nodes' ? '🗂️ Nodes' : '💻 Cypher'}
          </button>
        ))}
      </div>

      {tab === 'stats' && (
        <div>
          <button onClick={fetchStats} disabled={loading} className="btn btn-sm btn-primary mb-4">
            🔄 Refresh Stats
          </button>
          {stats ? (
            <div className="grid grid-cols-3 gap-4 mb-6">
              <div className="card p-4 text-center">
                <p className="text-3xl font-bold text-primary">{stats.total_nodes.toLocaleString()}</p>
                <p className="text-sm text-slate-400">Total Nodes</p>
              </div>
              <div className="card p-4 text-center">
                <p className="text-3xl font-bold text-secondary">{stats.total_relationships.toLocaleString()}</p>
                <p className="text-sm text-slate-400">Total Relationships</p>
              </div>
              <div className="card p-4 text-center">
                <p className="text-3xl font-bold text-accent">{stats.labels.length}</p>
                <p className="text-sm text-slate-400">Labels</p>
              </div>
            </div>
          ) : <p className="text-slate-400">กดปุ่ม Refresh Stats ก่อน</p>}

          {stats?.labels && (
            <div className="card p-4">
              <h3 className="font-semibold mb-3">Node Labels</h3>
              <table className="table w-full text-sm">
                <thead><tr><th>Label</th><th>Count</th></tr></thead>
                <tbody>
                  {stats.labels.map((l, i) => (
                    <tr key={i}><td className="font-mono text-primary">{l.label}</td><td>{l.count.toLocaleString()}</td></tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}

      {tab === 'nodes' && (
        <div>
          <h3 className="font-semibold mb-3">Query Presets</h3>
          <div className="flex flex-wrap gap-2 mb-4">
            {presets.map((p, i) => (
              <button key={i} onClick={() => { setCustomQuery(p.query); setTab('cypher') }}
                className="btn btn-sm btn-outline">{p.label}</button>
            ))}
          </div>
        </div>
      )}

      {tab === 'cypher' && (
        <div>
          <textarea
            className="textarea w-full font-mono text-sm"
            rows={5}
            value={customQuery}
            onChange={e => setCustomQuery(e.target.value)}
            placeholder="MATCH (n) RETURN n LIMIT 10"
          />
          <div className="flex gap-2 mt-2">
            <button onClick={runCypher} disabled={loading || !customQuery.trim()}
              className="btn btn-primary btn-sm">
              ▶ รัน Cypher
            </button>
          </div>
          {error && <p className="text-red-400 mt-2">{error}</p>}
          {queryResult && (
            <pre className="mt-4 p-4 bg-slate-900 rounded-lg overflow-auto text-xs max-h-96">
              {queryResult}
            </pre>
          )}
        </div>
      )}
    </div>
  )
}
