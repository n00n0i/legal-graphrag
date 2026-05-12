import { useState, useEffect } from 'react'

const API = '/api/v1'

function getToken() { return localStorage.getItem('lg_token') || '' }

interface Law {
  law_id: string
  title: string
  law_type: string
  uploaded_by: string
  uploaded_at: string
  total_chunks: number
  status: string
}

export default function DocsPage() {
  const [docs, setDocs] = useState<Law[]>([])
  const [loading, setLoading] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [error, setError] = useState('')
  const [uploadTitle, setUploadTitle] = useState('')
  const [selectedFile, setSelectedFile] = useState<File | null>(null)
  const [deleteId, setDeleteId] = useState<string | null>(null)
  const [reindexId, setReindexId] = useState<string | null>(null)

  async function fetchDocs() {
    setLoading(true)
    try {
      const r = await fetch(`${API}/admin/documents`, {
        headers: { Authorization: `Bearer ${getToken()}` }
      })
      if (r.ok) setDocs(await r.json())
      else setError(`Error ${r.status}`)
    } catch (e: any) { setError(e.message) }
    finally { setLoading(false) }
  }

  useEffect(() => { fetchDocs() }, [])

  async function handleUpload(e: React.FormEvent) {
    e.preventDefault()
    if (!selectedFile || !uploadTitle) return
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', selectedFile)
      fd.append('title', uploadTitle)
      fd.append('description', '')
      const r = await fetch(`${API}/admin/documents/upload`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${getToken()}` },
        body: fd,
      })
      if (r.ok) {
        setUploadTitle('')
        setSelectedFile(null)
        fetchDocs()
      } else {
        const err = await r.json()
        setError(err.detail?.error || `Error ${r.status}`)
      }
    } catch (e: any) { setError(e.message) }
    finally { setUploading(false) }
  }

  async function handleDelete(lawId: string) {
    if (!confirm('ลบเอกสารนี้?')) return
    const r = await fetch(`${API}/admin/documents/${lawId}`, {
      method: 'DELETE',
      headers: { Authorization: `Bearer ${getToken()}` }
    })
    if (r.ok) fetchDocs()
  }

  async function handleReindex(lawId: string) {
    const r = await fetch(`${API}/admin/documents/${lawId}/reindex`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${getToken()}` }
    })
    if (r.ok) alert('Reindex scheduled')
  }

  return (
    <div className="max-w-6xl mx-auto">
      <h1 className="text-2xl font-bold mb-6">📄 จัดการเอกสาร</h1>

      {/* Upload Form */}
      <form onSubmit={handleUpload} className="card mb-6 p-4">
        <h2 className="font-semibold mb-3">📤 อัพโหลดเอกสารใหม่</h2>
        <div className="flex gap-3 flex-wrap">
          <input
            className="input flex-1"
            placeholder="ชื่อเอกสาร (เช่น พระราชบัญญัติลาไม่เกินสิบวัน)"
            value={uploadTitle}
            onChange={e => setUploadTitle(e.target.value)}
            required
          />
          <input
            type="file"
            accept=".pdf,.docx,.doc"
            className="file-input file-input-bordered"
            onChange={e => setSelectedFile(e.target.files?.[0] || null)}
            required
          />
          <button type="submit" disabled={uploading} className="btn btn-primary">
            {uploading ? 'กำลังอัพโหลด...' : 'อัพโหลด + Ingest'}
          </button>
        </div>
        {error && <p className="text-red-400 mt-2">{error}</p>}
        <p className="text-xs text-slate-500 mt-2">รองรับ PDF/DOC/DOCX — ระบบจะ parse และ ingest เข้า Neo4j + Qdrant อัตโนมัติ</p>
      </form>

      {/* Docs List */}
      {loading ? (
        <div className="text-center py-12 text-slate-400">กำลังโหลด...</div>
      ) : docs.length === 0 ? (
        <div className="card text-center py-12 text-slate-400">
          <p className="text-4xl mb-3">📭</p>
          <p>ยังไม่มีเอกสาร — อัพโหลดอันแรกเลย!</p>
        </div>
      ) : (
        <div className="space-y-3">
          {docs.map(doc => (
            <div key={doc.law_id} className="card p-4 flex items-center justify-between">
              <div className="flex-1">
                <p className="font-semibold">{doc.title}</p>
                <p className="text-xs text-slate-400 mt-1">
                  {doc.law_type} • {doc.total_chunks} chunks • อัพโหลดโดย {doc.uploaded_by}
                  {' '}&bull; {new Date(doc.uploaded_at).toLocaleDateString('th-TH')}
                </p>
              </div>
              <div className="flex gap-2 ml-4">
                <button
                  onClick={() => handleReindex(doc.law_id)}
                  className="btn btn-xs btn-outline"
                  title="Re-index"
                >🔄 Reindex</button>
                <button
                  onClick={() => handleDelete(doc.law_id)}
                  className="btn btn-xs btn-error btn-outline"
                >🗑️ ลบ</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
