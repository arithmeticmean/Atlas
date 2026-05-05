import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { Badge, Button, Card, Spinner, inputCls, labelCls } from './ui.jsx'

const SYNC_TONE = { ok: 'ok', partial: 'warn', error: 'err' }

function fmtTime(iso) {
  if (!iso) return 'never'
  const d = new Date(iso)
  return isNaN(d) ? iso : d.toLocaleString()
}

export default function Connectors({ projectId }) {
  const [connectors, setConnectors] = useState([])
  const [error, setError] = useState('')

  const refresh = async () => {
    try {
      setConnectors(await api.listConnectors(projectId))
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }
  useEffect(() => { refresh() }, [projectId])

  return (
    <div>
      <CreateForm projectId={projectId} onCreated={refresh} />
      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      {connectors.length === 0 && (
        <Card className="text-dim">No connectors yet. Add one above.</Card>
      )}
      {connectors.map((c) => (
        <ConnectorCard key={c.id} projectId={projectId} connector={c} onChanged={refresh} />
      ))}
    </div>
  )
}

function CreateForm({ projectId, onCreated }) {
  const [open, setOpen] = useState(false)
  const [type, setType] = useState('url')
  const [name, setName] = useState('')
  const [urls, setUrls] = useState('')
  const [token, setToken] = useState('')
  const [fileIds, setFileIds] = useState('')
  const [baseUrl, setBaseUrl] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const lines = (s) => s.split('\n').map((x) => x.trim()).filter(Boolean)

  const submit = async () => {
    setBusy(true)
    setError('')
    try {
      let config
      if (type === 'url') config = { urls: lines(urls) }
      else {
        config = { access_token: token.trim(), file_ids: lines(fileIds) }
        if (baseUrl.trim()) config.base_url = baseUrl.trim()
      }
      await api.createConnector(projectId, { type, name: name.trim(), config })
      setName(''); setUrls(''); setToken(''); setFileIds(''); setBaseUrl('')
      setOpen(false)
      onCreated()
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  if (!open) {
    return (
      <Button variant="primary" className="mb-3.5" onClick={() => setOpen(true)}>
        + Add connector
      </Button>
    )
  }

  return (
    <Card>
      <div className="flex items-center justify-between">
        <strong>New connector</strong>
        <Button size="sm" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
      <label className={labelCls}>Type</label>
      <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)}>
        <option value="url">URL</option>
        <option value="google_drive">Google Drive</option>
      </select>
      <label className={labelCls}>Name</label>
      <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)}
        placeholder="e.g. Team wiki" />

      {type === 'url' ? (
        <>
          <label className={labelCls}>URLs (one per line)</label>
          <textarea className={inputCls} rows="3" value={urls}
            onChange={(e) => setUrls(e.target.value)}
            placeholder="https://example.com/doc.pdf" />
        </>
      ) : (
        <>
          <label className={labelCls}>OAuth access token</label>
          <input className={inputCls} value={token} onChange={(e) => setToken(e.target.value)}
            placeholder="ya29.… (expires ~1h)" />
          <label className={labelCls}>File IDs (one per line)</label>
          <textarea className={inputCls} rows="3" value={fileIds}
            onChange={(e) => setFileIds(e.target.value)} />
          <label className={labelCls}>Base URL (optional, for testing)</label>
          <input className={inputCls} value={baseUrl} onChange={(e) => setBaseUrl(e.target.value)} />
        </>
      )}

      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      <div className="mt-3">
        <Button variant="primary" onClick={submit} disabled={busy || !name.trim()}>
          {busy ? <Spinner /> : 'Create'}
        </Button>
      </div>
    </Card>
  )
}

function ConnectorCard({ projectId, connector, onChanged }) {
  const [health, setHealth] = useState(null)
  const [sync, setSync] = useState(null)
  const [busy, setBusy] = useState('')
  const [editing, setEditing] = useState(false)

  const doHealth = async () => {
    setBusy('health'); setHealth(null)
    try { setHealth(await api.connectorHealth(projectId, connector.id)) }
    catch (e) { setHealth({ healthy: false, detail: e.message }) }
    setBusy('')
  }
  const doSync = async () => {
    setBusy('sync'); setSync(null)
    try { setSync(await api.syncConnector(projectId, connector.id)) }
    catch (e) { setSync({ status: 'error', detail: e.message }) }
    setBusy('')
    onChanged()
  }
  const doDelete = async () => {
    if (!confirm(`Delete connector "${connector.name}"?`)) return
    await api.deleteConnector(projectId, connector.id)
    onChanged()
  }

  return (
    <Card>
      <div className="flex items-start justify-between gap-3 flex-wrap">
        <div>
          <strong>{connector.name}</strong>{' '}
          <Badge>{connector.type}</Badge>{' '}
          {!connector.enabled && <Badge tone="warn">disabled</Badge>}
          <div className="text-xs text-dim mt-2">
            Last sync: {fmtTime(connector.last_synced_at)}
            {connector.last_sync_status && (
              <>
                {' '}
                <Badge tone={SYNC_TONE[connector.last_sync_status] || 'dim'}>
                  {connector.last_sync_status}
                </Badge>{' '}
                {connector.last_sync_detail}
              </>
            )}
          </div>
        </div>
        <div className="flex items-center gap-2.5 flex-wrap">
          <Button size="sm" onClick={doHealth} disabled={!!busy}>
            {busy === 'health' ? <Spinner /> : 'Health'}
          </Button>
          <Button variant="primary" size="sm" onClick={doSync} disabled={!!busy}>
            {busy === 'sync' ? <Spinner /> : 'Sync now'}
          </Button>
          <Button size="sm" onClick={() => setEditing((v) => !v)}>Edit</Button>
          <Button variant="danger" size="sm" onClick={doDelete}>Delete</Button>
        </div>
      </div>

      {health && (
        <div className="text-xs mt-3">
          <Badge tone={health.healthy ? 'ok' : 'err'}>
            {health.healthy ? 'healthy' : 'unhealthy'}
          </Badge>{' '}
          {health.detail}
        </div>
      )}
      {sync && (
        <div className="text-xs mt-3">
          <Badge tone={SYNC_TONE[sync.status] || 'dim'}>{sync.status}</Badge>{' '}
          {sync.detail}
        </div>
      )}

      {editing && (
        <EditPanel projectId={projectId} connector={connector}
          onSaved={() => { setEditing(false); onChanged() }} />
      )}
    </Card>
  )
}

function EditPanel({ projectId, connector, onSaved }) {
  const [name, setName] = useState(connector.name)
  const [enabled, setEnabled] = useState(connector.enabled)
  const [configText, setConfigText] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const save = async () => {
    setBusy(true); setError('')
    try {
      const body = { name, enabled }
      if (configText.trim()) body.config = JSON.parse(configText)
      await api.updateConnector(projectId, connector.id, body)
      onSaved()
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  return (
    <div className="mt-3 pt-3 border-t border-line">
      <label className={labelCls}>Name</label>
      <input className={inputCls} value={name} onChange={(e) => setName(e.target.value)} />
      <label className="flex items-center gap-2.5 mt-3 text-sm text-ink">
        <input type="checkbox" className="w-auto accent-[var(--color-accent)]"
          checked={enabled} onChange={(e) => setEnabled(e.target.checked)} />
        <span>Enabled</span>
      </label>
      <label className={labelCls}>Replace config (JSON) — leave blank to keep current</label>
      <textarea className={`${inputCls} font-mono`} rows="3" value={configText}
        onChange={(e) => setConfigText(e.target.value)}
        placeholder={JSON.stringify(connector.config)} />
      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      <div className="mt-3">
        <Button variant="primary" onClick={save} disabled={busy}>
          {busy ? <Spinner /> : 'Save'}
        </Button>
      </div>
    </div>
  )
}
