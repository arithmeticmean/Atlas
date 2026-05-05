import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { appOrigin, inviteLink, isLoopbackHost } from '../lib/net.js'
import { Badge, Button, Card, Spinner, inputCls } from './ui.jsx'

const TH = 'text-left px-2 py-2.5 border-b border-line text-[11px] uppercase tracking-wide text-faint font-semibold'
const TD = 'text-left px-2 py-2.5 border-b border-line text-[13px] align-top'

// Project membership management (moderators only). Add existing users by email,
// remove them, or mint an invite link that both creates a new account and joins
// it to this project.
export default function Members({ project }) {
  const pid = project.id
  const isOwner = project.role === 'owner'
  const [members, setMembers] = useState([])
  const [error, setError] = useState('')

  const refresh = async () => {
    try {
      setMembers(await api.listMembers(pid))
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }
  useEffect(() => { refresh() }, [pid])

  return (
    <div>
      <AccessNote />
      <AddMember pid={pid} isOwner={isOwner} onAdded={refresh} />
      <InviteBox pid={pid} isOwner={isOwner} />

      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}

      <Card className="mt-3.5">
        <div className="flex items-center justify-between">
          <strong>{members.length} member{members.length === 1 ? '' : 's'}</strong>
          <Button size="sm" onClick={refresh}>Refresh</Button>
        </div>
        <table className="w-full border-collapse mt-3">
          <thead>
            <tr><th className={TH}>User</th><th className={TH}>Role</th><th className={TH}></th></tr>
          </thead>
          <tbody>
            {members.map((m) => (
              <tr key={m.user_id} className="transition hover:bg-white/[0.02]">
                <td className={TD}>
                  {m.email || <span className="text-dim">unknown</span>}
                  <div className="font-mono text-xs text-dim break-all">{m.username || m.user_id}</div>
                </td>
                <td className={TD}>
                  <Badge tone={m.role === 'admin' ? 'ok' : 'dim'}>{m.role}</Badge>
                </td>
                <td className={TD}>
                  <RemoveButton pid={pid} member={m} onRemoved={refresh} />
                </td>
              </tr>
            ))}
            {members.length === 0 && (
              <tr><td colSpan="3" className={`${TD} text-dim`}>No members yet.</td></tr>
            )}
          </tbody>
        </table>
      </Card>
    </div>
  )
}

function AddMember({ pid, isOwner, onAdded }) {
  const [email, setEmail] = useState('')
  const [role, setRole] = useState('member')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true); setError('')
    try {
      await api.addMember(pid, email.trim(), role)
      setEmail('')
      onAdded()
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  return (
    <Card>
      <strong>Add an existing user</strong>
      <div className="flex items-center gap-2.5 mt-3">
        <input className={inputCls} value={email} type="email" placeholder="their email"
          onChange={(e) => setEmail(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()} />
        <select className={`${inputCls} w-[130px]`} value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="member">member</option>
          {isOwner && <option value="admin">admin</option>}
        </select>
        <Button variant="primary" onClick={submit} disabled={busy || !email.trim()}>
          {busy ? <Spinner /> : 'Add'}
        </Button>
      </div>
      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      <div className="text-dim text-xs mt-3">
        The user must already have an account. To onboard someone new, use an
        invite below.
      </div>
    </Card>
  )
}

function InviteBox({ pid, isOwner }) {
  const [role, setRole] = useState('member')
  const [token, setTok] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [copied, setCopied] = useState('')

  const mint = async () => {
    setBusy(true); setError(''); setCopied('')
    try {
      const res = await api.createInvite(pid, role)
      setTok(res.invite_token)
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  const copy = async (what, value) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(what)
    } catch {
      /* clipboard blocked; the field is selectable */
    }
  }

  const link = token ? inviteLink(token) : ''
  const loopback = isLoopbackHost()

  return (
    <Card className="mt-3.5">
      <strong>Invite a new user</strong>
      <div className="flex items-center gap-2.5 mt-3">
        <select className={`${inputCls} w-[130px]`} value={role} onChange={(e) => setRole(e.target.value)}>
          <option value="member">member</option>
          {isOwner && <option value="admin">admin</option>}
        </select>
        <Button variant="primary" onClick={mint} disabled={busy}>
          {busy ? <Spinner /> : 'Generate invite'}
        </Button>
      </div>
      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      {token && (
        <div className="mt-3">
          <div className="text-dim text-xs">
            Send this link — it opens the sign-up form prefilled. The invite
            expires shortly.
          </div>
          <div className="flex items-center gap-2.5 mt-3">
            <input className={`${inputCls} font-mono`} readOnly value={link}
              onFocus={(e) => e.target.select()} />
            <Button onClick={() => copy('link', link)}>
              {copied === 'link' ? 'Copied' : 'Copy link'}
            </Button>
          </div>
          {loopback ? (
            <div className="rounded-lg px-3 py-2.5 text-[12.5px] leading-relaxed mt-2.5 bg-warn/[0.13] border border-warn/30 text-[#f4d488]">
              This link points at <span className="font-mono">{appOrigin()}</span>,
              which only works on this computer. To invite someone on another
              device, open Atlas here using this machine’s network address
              (e.g. <span className="font-mono">http://192.168.x.x:8000</span>), then
              generate the invite again — see “Access from other devices” above.
            </div>
          ) : (
            <div className="text-dim text-xs mt-3">
              Anyone on your network can open this link directly.
            </div>
          )}
          <details className="mt-3">
            <summary className="text-dim text-xs cursor-pointer">
              or share just the token (paste under “Have an invite?”)
            </summary>
            <div className="flex items-center gap-2.5 mt-3">
              <input className={`${inputCls} font-mono`} readOnly value={token}
                onFocus={(e) => e.target.select()} />
              <Button onClick={() => copy('token', token)}>
                {copied === 'token' ? 'Copied' : 'Copy'}
              </Button>
            </div>
          </details>
        </div>
      )}
    </Card>
  )
}

// How other devices reach this instance. Purely derived from the browser's
// current address, because the server (in Docker) can't know the host's LAN IP.
function AccessNote() {
  const origin = appOrigin()
  const loopback = isLoopbackHost()
  return (
    <Card>
      <div className="flex items-center justify-between">
        <strong>Access from other devices</strong>
        <Badge tone={loopback ? 'warn' : 'ok'}>
          {loopback ? 'this device only' : 'network-reachable'}
        </Badge>
      </div>
      {loopback ? (
        <div className="text-dim text-xs mt-3 leading-relaxed">
          You’re viewing Atlas at <span className="font-mono">{origin}</span>, so
          other devices can’t reach it and invite links won’t work off this
          machine. Find this computer’s network IP —{' '}
          <span className="font-mono">hostname -I</span> (Linux/macOS) or{' '}
          <span className="font-mono">ipconfig</span> (Windows) — then open Atlas at{' '}
          <span className="font-mono">http://&lt;that-ip&gt;:8000</span>. Everyone on
          the same Wi-Fi/LAN can use that address; invites generated from it will
          just work.
        </div>
      ) : (
        <div className="text-dim text-xs mt-3 leading-relaxed">
          Other devices on the same network can open Atlas at{' '}
          <span className="font-mono">{origin}</span>. Invite links you generate below
          use this address, so they’ll open directly on any device here.
        </div>
      )}
    </Card>
  )
}

function RemoveButton({ pid, member, onRemoved }) {
  const [busy, setBusy] = useState(false)
  const remove = async () => {
    if (!confirm(`Remove ${member.email || member.user_id} from this project?`)) return
    setBusy(true)
    try {
      await api.removeMember(pid, member.user_id)
      onRemoved()
    } finally {
      setBusy(false)
    }
  }
  return (
    <Button variant="danger" size="sm" onClick={remove} disabled={busy}>
      {busy ? <Spinner /> : 'Remove'}
    </Button>
  )
}
