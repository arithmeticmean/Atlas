import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { Badge, Button, Card } from './ui.jsx'

// Global diagnostics. Readiness is visible to anyone; the /status detail
// requires the owner account, so non-owners see a note instead.
export default function Health({ ready }) {
  const [status, setStatus] = useState(null)
  const [statusErr, setStatusErr] = useState('')

  const loadStatus = async () => {
    setStatusErr('')
    try {
      setStatus(await api.status())
    } catch (e) {
      setStatus(null)
      setStatusErr(
        e.status === 401 || e.status === 403
          ? 'Diagnostics are limited to the owner account.'
          : e.message,
      )
    }
  }

  useEffect(() => { loadStatus() }, [])

  return (
    <div>
      <Card>
        <strong>Readiness</strong>
        <div className="flex items-center gap-2.5 mt-3">
          <Badge tone={ready?.ready ? 'ok' : ready?.unreachable ? 'err' : 'warn'}>
            {ready?.unreachable ? 'offline' : ready?.ready ? 'ready' : 'not ready'}
          </Badge>
          {ready?.reindexing && <Badge tone="warn">reindexing</Badge>}
        </div>
        <div className="text-xs text-dim mt-3">
          Liveness <span className="font-mono">GET /api/health</span> · readiness{' '}
          <span className="font-mono">GET /api/health/ready</span>
        </div>
      </Card>

      <Card>
        <div className="flex items-center justify-between">
          <strong>Diagnostics <span className="text-dim text-xs">(/api/status · owner)</span></strong>
          <Button size="sm" onClick={loadStatus}>Refresh</Button>
        </div>

        {status ? (
          <>
            <div className="grid grid-cols-2 gap-3 mt-3">
              <Stat k="Embedding" v={status.embedding?.model}
                sub={`${status.embedding?.provider} · dim ${status.embedding?.dim}${status.embedding?.reindexing ? ' · reindexing' : ''}`} />
              <Stat k="LLM" v={status.llm?.model} sub={status.llm?.provider} />
            </div>
            <div className="mt-3 text-xs"><strong>Ingestion queue</strong></div>
            <div className="flex items-center gap-2.5 flex-wrap mt-3">
              {['queued', 'processing', 'done', 'failed'].map((s) => (
                <Badge key={s}>{s}: {status.queue?.[s] || 0}</Badge>
              ))}
            </div>
          </>
        ) : (
          <div className="text-dim text-xs mt-3">{statusErr}</div>
        )}
      </Card>
    </div>
  )
}

function Stat({ k, v, sub }) {
  return (
    <div className="bg-input border border-line rounded-lg p-3.5">
      <div className="text-faint text-[11px] uppercase tracking-wide">{k}</div>
      <div className="text-xl font-bold mt-1">{v}</div>
      <div className="text-xs text-dim">{sub}</div>
    </div>
  )
}
