import { useEffect, useMemo, useRef, useState } from 'react'
import { AlertCircle, CheckCircle2, Download, RefreshCw, Search, Trash2, UploadCloud, X } from 'lucide-react'
import { api } from '../lib/api.js'
import { extension, fileSize, fullDate, timeAgo } from '../lib/format.js'
import { useDebounced, useInterval, useLoad, usePaged } from '../lib/hooks.js'
import {
  Badge, Button, Card, compactSelect, cx, Empty, ErrorState, IconButton, inputClass, Page, PageHeader, SkeletonRows, Spinner, TextField, useConfirm, useToast,
} from '../ui/index.jsx'
import { canManage, useWorkspace } from './Shell.jsx'

const STATUS = {
  queued: { tone: 'neutral', label: 'Queued' },
  processing: { tone: 'accent', label: 'Indexing' },
  indexed: { tone: 'ok', label: 'Ready' },
  failed: { tone: 'bad', label: 'Failed' },
}

const StatusBadge = ({ status }) => (
  <Badge tone={STATUS[status].tone}>
    {status === 'processing' && <Spinner size={11} />}
    {STATUS[status].label}
  </Badge>
)

export default function Documents() {
  const { project } = useWorkspace()
  const pid = project.id
  const toast = useToast()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('')
  const [tag, setTag] = useState('')
  const [uploads, setUploads] = useState([])
  const [dragging, setDragging] = useState(false)
  const [openId, setOpenId] = useState(null)
  const input = useRef(null)
  const dragDepth = useRef(0)
  const search = useDebounced(q)

  const docs = usePaged(
    (cursor) => api.documents(pid, { cursor, limit: 50, q: search, status, tag }),
    [pid, search, status, tag],
  )
  const tags = useLoad(() => api.tags(pid), [pid])
  const types = useLoad(() => api.fileTypes(), [])
  const accept = useMemo(
    () => [...(types.data?.extractable || []), ...(types.data?.plain_text || [])].map((t) => (t.startsWith('.') ? t : `.${t}`)).join(','),
    [types.data],
  )

  const working = docs.items?.some((d) => d.status === 'queued' || d.status === 'processing')
  useInterval(async () => {
    const ids = docs.items.filter((d) => d.status === 'queued' || d.status === 'processing').map((d) => d.id)
    const fresh = await Promise.all(ids.map((id) => api.document(pid, id).catch(() => null)))
    docs.setItems((all) => all.map((d) => fresh.find((f) => f?.id === d.id) || d))
  }, working ? 1500 : null)

  const uploadFiles = async (files) => {
    const batch = [...files].map((file) => ({ id: crypto.randomUUID?.() ?? `${file.name}-${Math.random()}`, file, progress: 0, state: 'uploading' }))
    if (!batch.length) return
    setUploads((u) => [...batch, ...u])
    const patch = (id, change) => setUploads((u) => u.map((x) => (x.id === id ? { ...x, ...change } : x)))
    // Three at a time, so one big batch doesn't saturate the server.
    const queue = [...batch]
    const worker = async () => {
      for (let item = queue.shift(); item; item = queue.shift()) {
        try {
          const { document, duplicate } = await api.uploadDocument(pid, item.file, (progress) => patch(item.id, { progress }))
          patch(item.id, { state: duplicate ? 'duplicate' : 'done', progress: 1 })
          docs.setItems((all) => [document, ...all.filter((d) => d.id !== document.id)])
          const { id } = item
          setTimeout(() => setUploads((u) => u.filter((x) => x.id !== id)), 2500)
        } catch (e) {
          patch(item.id, { state: 'failed', error: e.message })
        }
      }
    }
    await Promise.all([worker(), worker(), worker()])
    tags.reload()
  }

  const onDrag = (event) => {
    if (!event.dataTransfer?.types?.includes('Files')) return
    event.preventDefault()
    if (event.type === 'dragenter') dragDepth.current++
    if (event.type === 'dragleave') dragDepth.current--
    if (event.type === 'drop') {
      dragDepth.current = 0
      uploadFiles(event.dataTransfer.files)
    }
    setDragging(dragDepth.current > 0)
  }

  const replace = (doc) => docs.setItems((all) => all.map((d) => (d.id === doc.id ? doc : d)))
  const filtered = Boolean(search || status || tag)
  const open = docs.items?.find((d) => d.id === openId)

  return (
    <div className="relative h-full" onDragEnter={onDrag} onDragOver={onDrag} onDragLeave={onDrag} onDrop={onDrag}>
      {dragging && (
        <div className="animate-fade pointer-events-none absolute inset-3 z-20 grid place-items-center rounded-2xl border-2 border-dashed border-accent bg-accent-soft/90">
          <div className="text-center text-accent">
            <UploadCloud size={34} className="mx-auto" />
            <p className="mt-2 font-serif text-2xl">Drop to add to {project.name}</p>
          </div>
        </div>
      )}
      <Page wide>
        <PageHeader title="Documents" description="Everything Atlas can read and cite in this project.">
          <input ref={input} type="file" multiple hidden accept={accept} onChange={(e) => { uploadFiles(e.target.files); e.target.value = '' }} />
          <Button variant="primary" icon={UploadCloud} onClick={() => input.current.click()}>Upload</Button>
        </PageHeader>

        {uploads.length > 0 && (
          <Card className="mb-4 divide-y divide-line">
            {uploads.map((u) => <UploadRow key={u.id} item={u} onDismiss={() => setUploads((all) => all.filter((x) => x.id !== u.id))} />)}
          </Card>
        )}

        <div className="mb-3 flex flex-wrap items-center gap-2">
          <div className="relative min-w-52 flex-1">
            <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
            <input aria-label="Search documents by title" className={cx(inputClass, 'h-9 pl-9')} placeholder="Search by title" value={q} onChange={(e) => setQ(e.target.value)} />
          </div>
          <select aria-label="Filter by status" className={cx(compactSelect, 'h-9')} value={status} onChange={(e) => setStatus(e.target.value)}>
            <option value="">All statuses</option>
            {Object.entries(STATUS).map(([key, s]) => <option key={key} value={key}>{s.label}</option>)}
          </select>
        </div>

        {tags.data?.length > 0 && (
          <div className="mb-3 flex flex-wrap gap-1.5">
            {tags.data.map((t) => (
              <button
                key={t.name}
                type="button"
                aria-pressed={tag === t.name}
                onClick={() => setTag(tag === t.name ? '' : t.name)}
                className={cx(
                  'h-7 rounded-full border px-2.5 text-xs transition',
                  tag === t.name ? 'border-accent bg-accent-soft text-accent' : 'border-line text-muted hover:border-line-strong',
                )}
              >
                {t.name} <span className="opacity-60">{t.count}</span>
              </button>
            ))}
          </div>
        )}

        <Card className="overflow-hidden">
          {docs.loading ? <SkeletonRows /> : docs.error ? <ErrorState error={docs.error} onRetry={docs.reload} /> : docs.items.length === 0 ? (
            filtered ? (
              <Empty icon={Search} title="Nothing matches">Try a different search or filter.</Empty>
            ) : (
              <Empty icon={UploadCloud} title="No documents yet" action={<Button variant="primary" onClick={() => input.current.click()}>Choose files</Button>}>
                Drop files anywhere on this page. PDFs, web pages, Markdown, code and plain text all work.
              </Empty>
            )
          ) : (
            <ul className="divide-y divide-line">
              {docs.items.map((doc) => (
                <li key={doc.id}>
                  <button type="button" onClick={() => setOpenId(doc.id)} className="flex w-full items-center gap-3 px-4 py-2.5 text-left transition hover:bg-raised/60">
                    <FileBadge title={doc.title} />
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{doc.title}</span>
                      <span className="flex items-center gap-1.5 truncate text-xs text-faint">
                        {fileSize(doc.size_bytes)} · {timeAgo(doc.created_at)}
                        {doc.tags.length > 0 && <span className="truncate">· {doc.tags.join(', ')}</span>}
                      </span>
                    </span>
                    <StatusBadge status={doc.status} />
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Card>
        {docs.hasMore && <div className="mt-4 text-center"><Button busy={docs.loadingMore} onClick={docs.loadMore}>Load more</Button></div>}
      </Page>
      {open && (
        <DocumentPanel
          key={open.id}
          doc={open}
          pid={pid}
          canDelete={canManage(project)}
          onChange={(doc) => { replace(doc); tags.reload() }}
          onDeleted={() => {
            docs.setItems((all) => all.filter((d) => d.id !== open.id))
            setOpenId(null)
            tags.reload()
            toast.ok('Document deleted')
          }}
          onClose={() => setOpenId(null)}
        />
      )}
    </div>
  )
}

const FileBadge = ({ title }) => (
  <span className="grid h-9 w-8 shrink-0 place-items-center rounded-md border border-line bg-canvas font-mono text-[8.5px] font-semibold uppercase text-muted">
    {extension(title)}
  </span>
)

function UploadRow({ item, onDismiss }) {
  const label = { uploading: `${Math.round(item.progress * 100)}%`, done: 'Added', duplicate: 'Already here' }[item.state]
  return (
    <div className="relative flex items-center gap-3 overflow-hidden px-4 py-2">
      {item.state === 'uploading' && <div className="absolute inset-y-0 left-0 bg-accent-soft transition-[width]" style={{ width: `${item.progress * 100}%` }} />}
      <span className="relative shrink-0">
        {item.state === 'uploading' ? <Spinner className="text-accent" /> : item.state === 'failed' ? <AlertCircle size={15} className="text-bad" /> : <CheckCircle2 size={15} className="text-ok" />}
      </span>
      <span className="relative min-w-0 flex-1 truncate text-[13px]">{item.file.name}</span>
      <span className={cx('relative max-w-[55%] truncate text-xs', item.state === 'failed' ? 'text-bad' : 'text-muted')} title={item.error}>{item.error || label}</span>
      {item.state === 'failed' && <IconButton icon={X} size={14} label="Dismiss" className="relative size-6" onClick={onDismiss} />}
    </div>
  )
}

function DocumentPanel({ doc, pid, canDelete, onChange, onDeleted, onClose }) {
  const toast = useToast()
  const confirm = useConfirm()
  const [title, setTitle] = useState(doc.title)
  const [tagText, setTagText] = useState('')
  const chunks = usePaged(
    (cursor) => (doc.status === 'indexed' ? api.chunks(pid, doc.id, { cursor, limit: 10 }) : Promise.resolve({ items: [], next_cursor: null })),
    [pid, doc.id, doc.status],
  )

  useEffect(() => {
    const onKey = (e) => e.key === 'Escape' && !document.querySelector('dialog[open]') && onClose()
    document.addEventListener('keydown', onKey)
    return () => document.removeEventListener('keydown', onKey)
  }, [onClose])

  const save = async (body) => {
    try {
      onChange(await api.updateDocument(pid, doc.id, body))
    } catch (e) {
      toast.error(e)
      setTitle(doc.title)
    }
  }
  const addTags = () => {
    const added = tagText.split(',').map((t) => t.trim().toLowerCase()).filter(Boolean)
    if (added.length) save({ tags: [...new Set([...doc.tags, ...added])] })
    setTagText('')
  }
  const reindex = async () => {
    try {
      onChange(await api.reindexDocument(pid, doc.id))
      toast.info('Queued for indexing')
    } catch (e) {
      toast.error(e)
    }
  }
  const remove = async () => {
    const yes = await confirm({ title: 'Delete this document?', message: `“${doc.title}” and its search index will be removed. Past answers keep their quoted passages.`, action: 'Delete', danger: true })
    if (!yes) return
    try {
      await api.deleteDocument(pid, doc.id)
      onDeleted()
    } catch (e) {
      toast.error(e)
    }
  }

  return (
    <>
      <div className="animate-fade fixed inset-0 z-30 bg-black/25" onClick={onClose} />
      <aside className="animate-slide fixed inset-y-0 right-0 z-30 flex w-full max-w-[460px] flex-col border-l border-line bg-surface shadow-float" aria-label="Document details">
        <div className="flex h-14 shrink-0 items-center justify-between gap-2 border-b border-line pl-5 pr-2">
          <StatusBadge status={doc.status} />
          <div className="flex items-center">
            <IconButton icon={Download} label="Download" onClick={() => api.downloadDocument(pid, doc).catch(toast.error)} />
            <IconButton icon={RefreshCw} label="Index again" onClick={reindex} />
            {canDelete && <IconButton icon={Trash2} label="Delete" className="hover:text-bad" onClick={remove} />}
            <IconButton icon={X} label="Close" onClick={onClose} />
          </div>
        </div>
        <div className="flex-1 space-y-5 overflow-y-auto p-5">
          {doc.status === 'failed' && (
            <div role="alert" className="rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">
              Indexing failed. Check the AI settings, then try indexing it again.
            </div>
          )}
          <TextField
            label="Title"
            value={title}
            maxLength={500}
            onChange={(e) => setTitle(e.target.value)}
            onBlur={() => title.trim() && title !== doc.title && save({ title: title.trim() })}
            onKeyDown={(e) => e.key === 'Enter' && e.currentTarget.blur()}
          />
          <div>
            <p className="mb-1.5 text-[13px] font-medium">Tags</p>
            <div className="flex min-h-10 flex-wrap items-center gap-1.5 rounded-lg border border-line-strong px-2 py-1.5 focus-within:border-accent">
              {doc.tags.map((t) => (
                <span key={t} className="inline-flex h-6 items-center gap-1 rounded bg-raised pl-2 pr-1 text-xs">
                  {t}
                  <button type="button" aria-label={`Remove ${t}`} className="text-faint hover:text-ink" onClick={() => save({ tags: doc.tags.filter((x) => x !== t) })}><X size={12} /></button>
                </span>
              ))}
              <input
                aria-label="Add a tag"
                className="h-6 min-w-20 flex-1 bg-transparent text-[13px] outline-none placeholder:text-faint"
                placeholder={doc.tags.length ? 'Add…' : 'Add a tag, press Enter'}
                value={tagText}
                maxLength={200}
                onChange={(e) => setTagText(e.target.value)}
                onBlur={addTags}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ',') {
                    e.preventDefault()
                    addTags()
                  }
                }}
              />
            </div>
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-[13px]">
            {[['Size', fileSize(doc.size_bytes)], ['Type', doc.mime_type || '—'], ['Added', fullDate(doc.created_at)], ['Indexed', fullDate(doc.indexed_at)]].map(([k, v]) => (
              <div key={k} className="min-w-0"><dt className="text-faint">{k}</dt><dd className="truncate" title={v}>{v}</dd></div>
            ))}
          </dl>
          <div>
            <h3 className="mb-2 text-[13px] font-medium">What Atlas read</h3>
            {doc.status !== 'indexed' ? (
              <p className="text-[13px] text-muted">Passages appear once indexing finishes.</p>
            ) : chunks.loading ? (
              <SkeletonRows rows={3} className="h-16" />
            ) : chunks.error ? (
              <p className="text-[13px] text-bad">{chunks.error.message}</p>
            ) : (
              <div className="space-y-2">
                {chunks.items.map((c) => (
                  <div key={c.index} className="rounded-lg bg-canvas p-3">
                    <p className="mb-1 font-mono text-[10.5px] text-faint">#{c.index + 1}{c.page > 0 ? ` · page ${c.page}` : ''}</p>
                    <p className="line-clamp-5 whitespace-pre-wrap break-words text-[13px] text-muted">{c.text}</p>
                  </div>
                ))}
                {chunks.hasMore && <Button size="sm" variant="ghost" busy={chunks.loadingMore} onClick={chunks.loadMore} className="w-full">Show more</Button>}
              </div>
            )}
          </div>
        </div>
      </aside>
    </>
  )
}
