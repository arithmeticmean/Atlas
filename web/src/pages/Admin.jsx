import { useState } from 'react'
import {
  CheckCircle2, Crown, Database, KeyRound, Link2, MoreHorizontal, Search, ShieldCheck, Trash2, UserPlus, UserX, XCircle,
} from 'lucide-react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { timeAgo } from '../lib/format.js'
import { useDebounced, useInterval, useLoad, usePaged } from '../lib/hooks.js'
import {
  Badge, Button, Card, compactSelect, cx, Empty, ErrorState, IconButton, inputClass, Menu, MenuItem, Modal, Notice, Page, PageHeader, SelectField, SkeletonRows, Spinner, TextField, useConfirm, useToast,
} from '../ui/index.jsx'
import { absoluteUrl, CopyField, InviteResult } from './shared.jsx'

// --- users ---------------------------------------------------------------------

const STATUS_TONE = { active: 'ok', pending: 'warn', disabled: 'bad' }

export function UsersAdmin() {
  const { user: me } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const [q, setQ] = useState('')
  const [inviting, setInviting] = useState(false)
  const [link, setLink] = useState(null)
  const search = useDebounced(q)
  const users = usePaged((cursor) => api.users({ cursor, limit: 50, q: search }), [search])
  const replace = (u) => users.setItems((all) => all.map((x) => (x.id === u.id ? u : x)))

  const update = async (user, body) => {
    try {
      replace(await api.updateUser(user.id, body))
    } catch (e) {
      toast.error(e)
    }
  }
  const remove = async (user) => {
    if (!(await confirm({ title: `Delete ${user.username}?`, message: 'Their account, memberships and chats are removed for good.', action: 'Delete', danger: true }))) return
    try {
      await api.deleteUser(user.id)
      users.setItems((all) => all.filter((u) => u.id !== user.id))
    } catch (e) {
      toast.error(e)
    }
  }
  const resetLink = async (user) => {
    try {
      const reset = await api.userResetLink(user.id)
      setLink({ user, url: absoluteUrl(reset.url) })
    } catch (e) {
      toast.error(e)
    }
  }
  const transfer = async (user) => {
    if (!(await confirm({ title: `Make ${user.username} the owner?`, message: 'You become an admin. Only the new owner can undo this.', action: 'Transfer ownership', danger: true }))) return
    try {
      await api.transferOwnership(user.id)
      window.location.reload()
    } catch (e) {
      toast.error(e)
    }
  }

  return (
    <Page>
      <PageHeader description="Everyone with an account on this server.">
        <Button variant="primary" icon={UserPlus} onClick={() => setInviting(true)}>Invite</Button>
      </PageHeader>
      <div className="relative mb-3">
        <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
        <input aria-label="Search users" className={cx(inputClass, 'h-9 pl-9')} placeholder="Search by name or email" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <Card className="overflow-visible">
        {users.loading ? <SkeletonRows /> : users.error ? <ErrorState error={users.error} onRetry={users.reload} /> : users.items.length === 0 ? (
          <Empty icon={Search} title="No one found" />
        ) : (
          <ul className="divide-y divide-line">
            {users.items.map((u) => {
              const self = u.id === me.id
              const locked = self || u.role === 'owner'
              return (
                <li key={u.id} className="flex items-center gap-3 px-4 py-2.5">
                  <span className="grid size-9 shrink-0 place-items-center rounded-full bg-raised font-medium uppercase">{u.username[0]}</span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{u.username}{self && <span className="font-normal text-faint"> (you)</span>}</span>
                    <span className="block truncate text-xs text-faint">{u.email} · {u.last_login_at ? `last seen ${timeAgo(u.last_login_at)}` : `joined ${timeAgo(u.created_at)}`}</span>
                  </span>
                  <Badge tone={STATUS_TONE[u.status]} className="max-sm:hidden">{u.status}</Badge>
                  {u.role === 'owner' ? (
                    <Badge tone="accent"><Crown size={11} /> Owner</Badge>
                  ) : (
                    <select aria-label={`Role for ${u.username}`} disabled={self} className={compactSelect} value={u.role} onChange={(e) => update(u, { role: e.target.value })}>
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                  )}
                  <Menu trigger={({ toggle }) => <IconButton icon={MoreHorizontal} label={`Options for ${u.username}`} disabled={self} onClick={toggle} />}>
                    {(close) => (
                      <>
                        <MenuItem icon={KeyRound} onClick={() => { close(); resetLink(u) }}>Password reset link</MenuItem>
                        {!locked && (u.status === 'disabled' ? (
                          <MenuItem icon={ShieldCheck} onClick={() => { close(); update(u, { status: 'active' }) }}>Enable</MenuItem>
                        ) : (
                          <MenuItem icon={UserX} onClick={() => { close(); update(u, { status: 'disabled' }) }}>Disable</MenuItem>
                        ))}
                        {me.role === 'owner' && u.status === 'active' && <MenuItem icon={Crown} onClick={() => { close(); transfer(u) }}>Make owner</MenuItem>}
                        {!locked && <MenuItem icon={Trash2} danger onClick={() => { close(); remove(u) }}>Delete</MenuItem>}
                      </>
                    )}
                  </Menu>
                </li>
              )
            })}
          </ul>
        )}
      </Card>
      {users.hasMore && <div className="mt-4 text-center"><Button busy={users.loadingMore} onClick={users.loadMore}>Load more</Button></div>}
      <InviteUser open={inviting} onClose={() => setInviting(false)} />
      <Modal open={Boolean(link)} onClose={() => setLink(null)} title={`Reset link for ${link?.user.username}`} description="Send this privately. It works once.">
        {link && <CopyField value={link.url} />}
      </Modal>
    </Page>
  )
}

function InviteUser({ open, onClose }) {
  const toast = useToast()
  const [role, setRole] = useState('member')
  const [email, setEmail] = useState('')
  const [invite, setInvite] = useState(null)
  const [busy, setBusy] = useState(false)
  const close = () => {
    setInvite(null)
    setEmail('')
    onClose()
  }
  const create = async () => {
    setBusy(true)
    try {
      setInvite(await api.createInvite({ role, email: email.trim() || null }))
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onClose={close} title="Invite someone" description="They create their own account from the link.">
      {invite ? <InviteResult invite={invite} /> : (
        <div className="space-y-3">
          <SelectField label="Instance role" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="member">Member: sees only their projects</option>
            <option value="admin">Admin: manages this server</option>
          </SelectField>
          <TextField label="Limit to one email (optional)" type="email" value={email} onChange={(e) => setEmail(e.target.value)} />
          <div className="flex justify-end pt-1"><Button variant="primary" busy={busy} icon={Link2} onClick={create}>Create link</Button></div>
        </div>
      )}
    </Modal>
  )
}

// --- system --------------------------------------------------------------------

export function SystemStatus() {
  const status = useLoad(() => api.status(), [])
  const network = useLoad(() => api.network(), [])
  useInterval(status.reload, 5000)
  const s = status.data

  if (status.error && !s) return <Page><ErrorState error={status.error} onRetry={status.reload} /></Page>
  if (!s) return <Page><Card><SkeletonRows rows={4} /></Card></Page>

  const queue = ['queued', 'processing', 'done', 'failed'].filter((k) => k in s.queue)
  return (
    <Page>
      <PageHeader description="Live health of this Atlas server.">
        <Badge tone={s.readiness.ready ? 'ok' : 'warn'} className="h-7 px-2.5 normal-case">
          {s.readiness.ready ? 'All systems ready' : s.readiness.reindexing ? 'Reindexing' : 'Degraded'}
        </Badge>
      </PageHeader>
      <div className="grid gap-3 sm:grid-cols-2">
        {[['Chat model', s.llm], ['Embedding model', s.embedding]].map(([label, p]) => (
          <Card key={label} className="p-4">
            <div className="flex items-center justify-between">
              <span className="text-[13px] text-muted">{label}</span>
              {p.ok ? <CheckCircle2 size={16} className="text-ok" /> : <XCircle size={16} className="text-bad" />}
            </div>
            <p className="mt-1 truncate font-medium" title={p.model}>{p.model}</p>
            <p className="truncate text-xs text-faint" title={p.detail}>{p.provider} · {p.detail}</p>
          </Card>
        ))}
        <Stat icon={Database} label="Indexed passages" value={s.index_chunks?.toLocaleString() ?? '—'} />
        <Card className="p-4">
          <span className="text-[13px] text-muted">Ingestion queue</span>
          <div className="mt-1.5 flex flex-wrap gap-1.5">
            {queue.length ? queue.map((k) => <Badge key={k} tone={k === 'failed' && s.queue[k] ? 'bad' : 'neutral'}>{k} {s.queue[k]}</Badge>) : <span className="text-[13px] text-faint">Empty</span>}
          </div>
        </Card>
      </div>
      <Card className="mt-3 divide-y divide-line text-[13px]">
        {[
          ['Version', s.version],
          ['Database schema', s.schema_version || '—'],
          ['Listening on', network.data ? `${network.data.bound_host}:${network.data.port}` : '…'],
          ['Reachable from', network.data ? (network.data.loopback_only ? 'This computer only' : network.data.addresses.join(', ') || 'Network') : '…'],
        ].map(([k, v]) => (
          <div key={k} className="flex justify-between gap-4 px-4 py-2.5">
            <span className="text-muted">{k}</span>
            <span className="truncate font-mono text-xs">{v}</span>
          </div>
        ))}
      </Card>
      {status.error && <Notice tone="warn" className="mt-3">Showing the last known status. <Spinner size={12} className="inline" /></Notice>}
    </Page>
  )
}

const Stat = ({ icon: Icon, label, value }) => (
  <Card className="p-4">
    <div className="flex items-center justify-between text-[13px] text-muted">{label}<Icon size={15} /></div>
    <p className="mt-1 font-serif text-[26px] leading-tight">{value}</p>
  </Card>
)
