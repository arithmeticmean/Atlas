import { useEffect, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { Badge, Button, Card, cx } from './ui.jsx'

const STATUS_TONE = {
  indexed: 'ok',
  queued: 'warn',
  processing: 'warn',
  failed: 'err',
}

const TH = 'text-left px-2 py-2.5 border-b border-line text-[11px] uppercase tracking-wide text-faint font-semibold'
const TD = 'text-left px-2 py-2.5 border-b border-line text-[13px] align-top'

export default function Documents({ projectId }) {
  const [docs, setDocs] = useState([])
  const [error, setError] = useState('')
  const [drag, setDrag] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  const refresh = async () => {
    try {
      setDocs(await api.listDocuments(projectId))
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    refresh()
    const id = setInterval(refresh, 3000)
    return () => clearInterval(id)
  }, [projectId])

  const upload = async (files) => {
    setUploading(true)
    setError('')
    try {
      for (const file of files) await api.uploadDocument(projectId, file)
      await refresh()
    } catch (e) {
      setError(e.message)
    }
    setUploading(false)
  }

  const onDrop = (e) => {
    e.preventDefault()
    setDrag(false)
    if (e.dataTransfer.files.length) upload([...e.dataTransfer.files])
  }

  return (
    <div>
      <div
        className={cx(
          'rounded-xl p-[30px] text-center border border-dashed transition cursor-pointer',
          drag
            ? 'border-accent bg-accent/15 text-ink'
            : 'border-line-2 text-dim bg-white/[0.01] hover:border-accent hover:text-ink',
        )}
        onDragOver={(e) => { e.preventDefault(); setDrag(true) }}
        onDragLeave={() => setDrag(false)}
        onDrop={onDrop}
        onClick={() => fileRef.current?.click()}
      >
        {uploading
          ? 'uploading…'
          : 'Drop files here, or click to choose. (txt, md, html, pdf, docx)'}
        <input
          ref={fileRef}
          type="file"
          multiple
          className="hidden"
          onChange={(e) => e.target.files.length && upload([...e.target.files])}
        />
      </div>

      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}

      <Card className="mt-3.5">
        <div className="flex items-center justify-between">
          <strong>{docs.length} document{docs.length === 1 ? '' : 's'}</strong>
          <Button size="sm" onClick={refresh}>Refresh</Button>
        </div>
        <table className="w-full border-collapse mt-3">
          <thead>
            <tr>
              <th className={TH}>Title</th>
              <th className={TH}>Type</th>
              <th className={TH}>Status</th>
              <th className={TH}></th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id} className="transition hover:bg-white/[0.02]">
                <td className={TD}>
                  {d.title}
                  <div className="font-mono text-xs text-dim break-all">{d.id}</div>
                </td>
                <td className={`${TD} text-dim text-xs`}>{d.mime_type || '—'}</td>
                <td className={TD}>
                  <Badge tone={STATUS_TONE[d.status] || 'dim'}>{d.status}</Badge>
                </td>
                <td className={TD}>
                  {d.status === 'failed' && (
                    <Button
                      size="sm"
                      onClick={async () => {
                        await api.reingest(projectId, d.id)
                        refresh()
                      }}
                    >
                      Retry
                    </Button>
                  )}
                </td>
              </tr>
            ))}
            {docs.length === 0 && (
              <tr><td colSpan="4" className={`${TD} text-dim`}>Nothing ingested yet.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  )
}
