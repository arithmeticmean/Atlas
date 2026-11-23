import { useState } from 'react'
import { Link2, Search, Trash2, UserPlus, Users } from 'lucide-react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { timeAgo } from '../lib/format.js'
import { useDebounced, useLoad, usePaged } from '../lib/hooks.js'
import {
  Badge, Button, Card, compactSelect, cx, Empty, ErrorState, IconButton, inputClass, Modal, Page, PageHeader, SelectField, SkeletonRows, Spinner, useConfirm, useToast,
} from '../ui/index.jsx'
import { InviteResult } from './shared.jsx'
import { canManage, useWorkspace } from './Shell.jsx'

export default function Members() {
  const { project } = useWorkspace()
  const { user: me } = useAuth()
  const toast = useToast()
  const confirm = useConfirm()
  const pid = project.id
  const manage = canManage(project)
  const [adding, setAdding] = useState(false)
  const [inviting, setInviting] = useState(false)
  const members = usePaged((cursor) => api.members(pid, { cursor, limit: 50 }), [pid])

  const setRole = async (member, role) => {
    try {
      const saved = await api.setMemberRole(pid, member.user_id, role)
      members.setItems((all) => all.map((m) => (m.user_id === saved.user_id ? saved : m)))
    } catch (e) {
      toast.error(e)
    }
  }
  const remove = async (member) => {
    const name = member.user?.username || 'this person'
    if (!(await confirm({ title: `Remove ${name}?`, message: `They lose access to ${project.name}. Their account stays.`, action: 'Remove', danger: true }))) return
    try {
      await api.removeMember(pid, member.user_id)
      members.setItems((all) => all.filter((m) => m.user_id !== member.user_id))
    } catch (e) {
      toast.error(e)
    }
  }

  return (
    <Page>
      <PageHeader title="Members" description={`People who can ask questions in ${project.name}.`}>
        {manage && (
          <>
            <Button icon={Link2} onClick={() => setInviting(true)}>Invite link</Button>
            <Button variant="primary" icon={UserPlus} onClick={() => setAdding(true)}>Add person</Button>
          </>
        )}
      </PageHeader>
      <Card className="overflow-hidden">
        {members.loading ? <SkeletonRows /> : members.error ? <ErrorState error={members.error} onRetry={members.reload} /> : members.items.length === 0 ? (
          <Empty icon={Users} title="Just you, for now">Instance admins can already see this project. Invite others to share it.</Empty>
        ) : (
          <ul className="divide-y divide-line">
            {members.items.map((m) => (
              <li key={m.user_id} className="flex items-center gap-3 px-4 py-2.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-full bg-raised font-medium uppercase">{m.user?.username?.[0] || '?'}</span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">
                    {m.user?.username || 'Deleted account'}
                    {m.user_id === me.id && <span className="font-normal text-faint"> (you)</span>}
                  </span>
                  <span className="block truncate text-xs text-faint">{m.user?.email} · joined {timeAgo(m.created_at)}</span>
                </span>
                {manage ? (
                  <>
                    <select aria-label={`Role for ${m.user?.username}`} className={compactSelect} value={m.role} onChange={(e) => setRole(m, e.target.value)}>
                      <option value="member">Member</option>
                      <option value="admin">Admin</option>
                    </select>
                    <IconButton icon={Trash2} label={`Remove ${m.user?.username}`} className="hover:text-bad" onClick={() => remove(m)} />
                  </>
                ) : (
                  <Badge tone={m.role === 'admin' ? 'accent' : 'neutral'}>{m.role}</Badge>
                )}
              </li>
            ))}
          </ul>
        )}
      </Card>
      {members.hasMore && <div className="mt-4 text-center"><Button busy={members.loadingMore} onClick={members.loadMore}>Load more</Button></div>}
      <AddPerson open={adding} onClose={() => setAdding(false)} pid={pid} existing={members.items || []} onAdded={(m) => members.setItems((all) => [...all, m])} />
      <InviteToProject open={inviting} onClose={() => setInviting(false)} project={project} />
    </Page>
  )
}

function AddPerson({ open, onClose, pid, existing, onAdded }) {
  const toast = useToast()
  const [q, setQ] = useState('')
  const [role, setRole] = useState('member')
  const [adding, setAdding] = useState(null)
  const query = useDebounced(q.trim())
  const results = useLoad(async () => (query ? api.lookupUsers(query) : []), [query])
  const available = (results.data || []).filter((u) => !existing.some((m) => m.user_id === u.id))

  const add = async (user) => {
    setAdding(user.id)
    try {
      onAdded(await api.addMember(pid, { user_id: user.id, role }))
      toast.ok(`${user.username} added`)
      setQ('')
      onClose()
    } catch (e) {
      toast.error(e)
    } finally {
      setAdding(null)
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="Add a person" description="Search people who already have an Atlas account.">
      <div className="space-y-3">
        <div className="relative">
          <Search size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-faint" />
          <input autoFocus aria-label="Search people" className={cx(inputClass, 'pl-9')} placeholder="Name or email" value={q} onChange={(e) => setQ(e.target.value)} />
        </div>
        <SelectField label="Role" value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="member">Member: chat and add documents</option>
          <option value="admin">Admin: also manage people and connectors</option>
        </SelectField>
        <div className="min-h-16">
          {results.loading && query ? (
            <div className="grid h-16 place-items-center text-muted"><Spinner /></div>
          ) : query && available.length === 0 ? (
            <p className="py-4 text-center text-[13px] text-muted">No one found. Send an invite link instead.</p>
          ) : (
            <ul className="space-y-0.5">
              {available.map((u) => (
                <li key={u.id}>
                  <button type="button" disabled={Boolean(adding)} onClick={() => add(u)} className="flex w-full items-center gap-2.5 rounded-lg p-2 text-left transition hover:bg-raised">
                    <span className="grid size-8 place-items-center rounded-full bg-raised font-medium uppercase">{u.username[0]}</span>
                    <span className="min-w-0 flex-1">
                      <span className="block truncate font-medium">{u.username}</span>
                      <span className="block truncate text-xs text-faint">{u.email}</span>
                    </span>
                    {adding === u.id ? <Spinner /> : <UserPlus size={15} className="text-muted" />}
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  )
}

function InviteToProject({ open, onClose, project }) {
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
      setInvite(await api.createInvite({ email: email.trim() || null, projects: [{ project_id: project.id, role }] }))
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onClose={close} title={`Invite to ${project.name}`} description="Anyone with the link can join until it expires.">
      {invite ? <InviteResult invite={invite} /> : (
        <div className="space-y-3">
          <SelectField label="They join as" value={role} onChange={(e) => setRole(e.target.value)}>
            <option value="member">Member</option>
            <option value="admin">Admin</option>
          </SelectField>
          <div>
            <label htmlFor="invite-email" className="mb-1.5 block text-[13px] font-medium">Limit to one email <span className="font-normal text-faint">(optional)</span></label>
            <input id="invite-email" type="email" className={inputClass} value={email} onChange={(e) => setEmail(e.target.value)} placeholder="teammate@company.com" />
          </div>
          <div className="flex justify-end pt-1"><Button variant="primary" busy={busy} onClick={create}>Create link</Button></div>
        </div>
      )}
    </Modal>
  )
}
