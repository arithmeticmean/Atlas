import { useState } from 'react'
import { CheckCircle2, Globe, HardDrive, MoreHorizontal, Plug, Plus, RefreshCw, Trash2, XCircle, Zap } from 'lucide-react'
import { api } from '../lib/api.js'
import { timeAgo } from '../lib/format.js'
import { useLoad, usePaged } from '../lib/hooks.js'
import {
  Badge, Button, Card, Empty, ErrorState, Field, IconButton, inputClass, Menu, MenuItem, Modal, Notice, Page, PageHeader, PasswordField, SkeletonRows, TextField, useConfirm, useToast,
} from '../ui/index.jsx'
import { useWorkspace } from './Shell.jsx'

const ICONS = { url: Globe, google_drive: HardDrive }
const SYNC_TONE = { succeeded: 'ok', partial: 'warn', failed: 'bad', running: 'accent' }
const pretty = (name) =>
  name === 'urls' ? 'URLs' : name.replace(/_/g, ' ').replace(/^./, (c) => c.toUpperCase())

export default function Connectors() {
  const { project } = useWorkspace()
  const pid = project.id
  const toast = useToast()
  const confirm = useConfirm()
  const [adding, setAdding] = useState(false)
  const [syncing, setSyncing] = useState({})
  const types = useLoad(() => api.connectorTypes(), [])
  const list = usePaged((cursor) => api.connectors(pid, { cursor, limit: 50 }), [pid])
  const replace = (c) => list.setItems((all) => all.map((x) => (x.id === c.id ? c : x)))

  const sync = async (connector) => {
    setSyncing((s) => ({ ...s, [connector.id]: true }))
    try {
      const r = await api.syncConnector(pid, connector.id)
      const summary = `${r.imported} imported, ${r.unchanged} unchanged, ${r.failed} failed`
      if (r.status === 'succeeded') toast.ok(summary)
      else toast.error(r.errors[0]?.message ? `${summary}. ${r.errors[0].message}` : summary)
      list.reload()
    } catch (e) {
      toast.error(e)
    } finally {
      setSyncing((s) => ({ ...s, [connector.id]: false }))
    }
  }
  const test = async (connector) => {
    try {
      const r = await api.testConnector(pid, connector.id)
      if (r.ok) toast.ok(r.detail || 'Connection works')
      else toast.error(r.detail)
    } catch (e) {
      toast.error(e)
    }
  }
  const toggle = async (connector) => {
    try {
      replace(await api.updateConnector(pid, connector.id, { enabled: !connector.enabled }))
    } catch (e) {
      toast.error(e)
    }
  }
  const remove = async (connector) => {
    if (!(await confirm({ title: `Delete ${connector.name}?`, message: 'Documents it already imported stay in the project.', action: 'Delete', danger: true }))) return
    try {
      await api.deleteConnector(pid, connector.id)
      list.setItems((all) => all.filter((c) => c.id !== connector.id))
    } catch (e) {
      toast.error(e)
    }
  }

  return (
    <Page>
      <PageHeader title="Connectors" description="Bring documents in from the web and other services.">
        <Button variant="primary" icon={Plus} onClick={() => setAdding(true)}>Add connector</Button>
      </PageHeader>
      {list.loading ? <Card><SkeletonRows rows={3} className="h-16" /></Card> : list.error ? <ErrorState error={list.error} onRetry={list.reload} /> : list.items.length === 0 ? (
        <Card>
          <Empty icon={Plug} title="No connectors yet" action={<Button variant="primary" onClick={() => setAdding(true)}>Add connector</Button>}>
            Pull in web pages or Google Drive files, and sync them whenever they change.
          </Empty>
        </Card>
      ) : (
        <div className="space-y-2.5">
          {list.items.map((c) => {
            const Icon = ICONS[c.type] || Plug
            return (
              <Card key={c.id} className="flex items-center gap-3 p-3.5">
                <span className="grid size-10 shrink-0 place-items-center rounded-lg bg-raised text-muted"><Icon size={18} /></span>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate font-medium">{c.name}</span>
                    {!c.enabled && <Badge>Paused</Badge>}
                    {c.last_sync_status && <Badge tone={SYNC_TONE[c.last_sync_status]}>{c.last_sync_status}</Badge>}
                  </div>
                  <p className="truncate text-xs text-faint">
                    {c.last_synced_at ? `Synced ${timeAgo(c.last_synced_at)}` : 'Never synced'}
                    {c.last_sync_detail && ` · ${c.last_sync_detail}`}
                  </p>
                </div>
                <Button size="sm" icon={RefreshCw} busy={syncing[c.id]} disabled={!c.enabled} onClick={() => sync(c)}>Sync</Button>
                <Menu trigger={({ toggle: open }) => <IconButton icon={MoreHorizontal} label={`Options for ${c.name}`} onClick={open} />}>
                  {(close) => (
                    <>
                      <MenuItem icon={Zap} onClick={() => { close(); test(c) }}>Test connection</MenuItem>
                      <MenuItem icon={c.enabled ? XCircle : CheckCircle2} onClick={() => { close(); toggle(c) }}>{c.enabled ? 'Pause' : 'Resume'}</MenuItem>
                      <MenuItem icon={Trash2} danger onClick={() => { close(); remove(c) }}>Delete</MenuItem>
                    </>
                  )}
                </Menu>
              </Card>
            )
          })}
        </div>
      )}
      {adding && types.data && (
        <AddConnector
          pid={pid}
          types={types.data}
          onClose={() => setAdding(false)}
          onCreated={(c) => {
            list.setItems((all) => [c, ...all])
            setAdding(false)
            sync(c)
          }}
        />
      )}
    </Page>
  )
}

/** Fields come from the connector's JSON Schema, so a new connector type
 *  needs no UI work. */
function schemaFields(type) {
  const { properties = {}, required = [] } = type.config_schema
  return Object.entries(properties)
    .filter(([name, spec]) => required.includes(name) || !('default' in spec))
    .map(([name, spec]) => ({
      name,
      label: spec.title || pretty(name),
      hint: spec.description,
      list: spec.type === 'array',
      secret: type.secret_fields.includes(name),
      required: required.includes(name),
    }))
}

function AddConnector({ pid, types, onClose, onCreated }) {
  const toast = useToast()
  const [typeKey, setTypeKey] = useState(types[0]?.type)
  const [name, setName] = useState('')
  const [values, setValues] = useState({})
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState(null)
  const type = types.find((t) => t.type === typeKey)
  const fields = schemaFields(type)

  const payload = () => {
    const config = {}
    const secrets = {}
    for (const field of fields) {
      const raw = (values[field.name] || '').trim()
      if (!raw) continue
      if (field.secret) secrets[field.name] = raw
      else config[field.name] = field.list ? raw.split(/\s*[\n,]\s*/).filter(Boolean) : raw
    }
    return { type: typeKey, config, secrets }
  }
  const test = async () => {
    setResult(null)
    try {
      setResult(await api.testConnectorDraft(pid, payload()))
    } catch (e) {
      setResult({ ok: false, detail: e.message })
    }
  }
  const create = async (event) => {
    event.preventDefault()
    setBusy(true)
    try {
      onCreated(await api.createConnector(pid, { ...payload(), name: name.trim() }))
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal
      open
      wide
      onClose={onClose}
      title="Add a connector"
      footer={
        <>
          <Button className="mr-auto" icon={Zap} onClick={test}>Test</Button>
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" form="connector-form" variant="primary" busy={busy}>Add and sync</Button>
        </>
      }
    >
      <form id="connector-form" onSubmit={create} className="space-y-4">
        <div className="grid gap-2 sm:grid-cols-2">
          {types.map((t) => {
            const Icon = ICONS[t.type] || Plug
            const active = t.type === typeKey
            return (
              <button
                key={t.type}
                type="button"
                aria-pressed={active}
                onClick={() => { setTypeKey(t.type); setValues({}); setResult(null) }}
                className={`rounded-xl border p-3 text-left transition ${active ? 'border-accent bg-accent-soft/50' : 'border-line hover:border-line-strong'}`}
              >
                <Icon size={17} className={active ? 'text-accent' : 'text-muted'} />
                <p className="mt-1.5 font-medium">{t.name}</p>
                <p className="text-xs text-muted">{t.description}</p>
              </button>
            )
          })}
        </div>
        <TextField label="Name" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} placeholder="Company handbook" />
        {fields.map((field) => {
          const onChange = (e) => setValues((v) => ({ ...v, [field.name]: e.target.value }))
          if (field.secret) {
            return <PasswordField key={field.name} label={field.label} hint={field.hint} required={field.required} autoComplete="off" value={values[field.name] || ''} onChange={onChange} />
          }
          if (field.list) {
            return (
              <Field key={field.name} label={field.label} hint={`${field.hint ? `${field.hint}. ` : ''}One per line.`}>
                {(id) => <textarea id={id} rows={3} required={field.required} className={`${inputClass} h-auto py-2 font-mono text-[13px]`} value={values[field.name] || ''} onChange={onChange} />}
              </Field>
            )
          }
          return <TextField key={field.name} label={field.label} hint={field.hint} required={field.required} value={values[field.name] || ''} onChange={onChange} />
        })}
        {result && <Notice tone={result.ok ? 'ok' : 'bad'}>{result.detail || (result.ok ? 'Connection works' : 'Connection failed')}</Notice>}
      </form>
    </Modal>
  )
}
