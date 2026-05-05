import { useState } from 'react'
import { api } from '../lib/api.js'
import { Badge, Button, Card, Spinner, inputCls } from './ui.jsx'

// Raw retrieval: shows the nearest chunks and their distance scores.
export default function Search({ projectId }) {
  const [query, setQuery] = useState('')
  const [k, setK] = useState(5)
  const [hits, setHits] = useState(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const run = async () => {
    const q = query.trim()
    if (!q) return
    setBusy(true)
    setError('')
    try {
      const res = await api.search(projectId, q, Number(k))
      setHits(res.hits)
    } catch (e) {
      setError(e.message)
      setHits(null)
    }
    setBusy(false)
  }

  return (
    <div>
      <Card>
        <div className="flex items-center gap-2.5">
          <input
            className={inputCls}
            value={query}
            placeholder="Search the index…"
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && run()}
          />
          <input
            className={`${inputCls} w-20`}
            type="number"
            min="1"
            max="50"
            value={k}
            onChange={(e) => setK(e.target.value)}
          />
          <Button variant="primary" onClick={run} disabled={busy || !query.trim()}>
            {busy ? <Spinner /> : 'Search'}
          </Button>
        </div>
        {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      </Card>

      {hits && hits.length === 0 && <Card className="text-dim">No results.</Card>}
      {hits &&
        hits.map((h, i) => (
          <Card key={i}>
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs text-dim">{h.document_id}</span>
              <Badge>chunk {h.chunk_index} · dist {h.score.toFixed(4)}</Badge>
            </div>
            <div className="mt-3 text-xs">{h.text}</div>
          </Card>
        ))}
    </div>
  )
}
