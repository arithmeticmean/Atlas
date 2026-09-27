import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { reachUrl } from '../lib/net.js'
import { Avatar } from './Avatar.jsx'
import { Button, Spinner, cx, inputCls, labelCls } from './ui.jsx'

// The API sends a naive UTC timestamp; render it in the viewer's locale
// rather than dumping the ISO string.
function formatJoined(iso) {
  const at = new Date(iso.endsWith('Z') ? iso : `${iso}Z`)
  if (Number.isNaN(at.getTime())) return iso
  return at.toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}

const ROLE_HELP = {
  admin: 'Can add and remove people, and manage connectors.',
  member: 'Can read, search and upload documents.',
}

// The context rail: whoever is selected, or the add flow when nobody is.
//
// Same idiom as the chat's source rail, so the two pages read as one app: the
// list keeps the left, and what you are doing with a row happens on the right
// instead of in a modal or a form stacked above the list.
export default function MemberRail({
  pid,
  selected,
  canModerate,
  isOwner,
  isSelf,
  net,
  memberIds,
  onChanged,
  onCleared,
}) {
  if (selected) {
    return (
      <RailShell>
        <PersonPanel
          pid={pid}
          member={selected}
          isOwner={isOwner}
          isSelf={isSelf}
          onChanged={onChanged}
          onCleared={onCleared}
        />
      </RailShell>
    )
  }
  return (
    <RailShell>
      <AddPanel
        pid={pid}
        isOwner={isOwner}
        canModerate={canModerate}
        net={net}
        memberIds={memberIds}
        onAdded={onChanged}
      />
    </RailShell>
  )
}

function RailShell({ children }) {
  return (
    <aside
      className="w-[400px] shrink-0 border-l border-line bg-input flex flex-col"
      aria-label="Member details"
    >
      <div className="flex-1 min-h-0 overflow-y-auto">{children}</div>
    </aside>
  )
}

function PersonPanel({ pid, member, isOwner, isSelf, onChanged, onCleared }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  // add_member upserts, so a role change is the same call as adding.
  const setRole = async (role) => {
    if (role === member.role) return
    setBusy(true)
    setError('')
    try {
      await api.addMember(pid, member.email, role)
      await onChanged()
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  const remove = async () => {
    const warning = isSelf
      ? 'Remove yourself from this project? You lose access immediately, ' +
        'and only the instance owner can add you back.'
      : `Remove ${member.email || member.user_id} from this project?`
    if (!confirm(warning)) return
    setBusy(true)
    setError('')
    try {
      await api.removeMember(pid, member.user_id)
      onCleared()
      await onChanged()
    } catch (e) {
      setError(e.message)
      setBusy(false)
    }
  }

  return (
    <div className="p-5">
      <div className="flex items-center gap-3.5">
        <Avatar email={member.email || member.user_id} size={44} />
        <div className="min-w-0">
          <div className="text-[15px] font-semibold truncate">
            {member.email || 'unknown'}
          </div>
          {member.username && (
            <div className="text-xs text-dim mt-0.5 truncate">
              {member.username}
            </div>
          )}
        </div>
      </div>

      <div className="h-px bg-line my-4.5" />

      <label className={labelCls} htmlFor="rail-role">
        Role on this project
      </label>
      {isOwner && member.email ? (
        <select
          id="rail-role"
          className={inputCls}
          value={member.role}
          disabled={busy}
          onChange={(e) => setRole(e.target.value)}
        >
          <option value="member">member</option>
          <option value="admin">admin</option>
        </select>
      ) : (
        <div className="text-[13.5px]">{member.role}</div>
      )}
      <p className="text-dim text-[11.5px] leading-relaxed mt-2">
        {ROLE_HELP[member.role]}
        {!isOwner && member.email && ' Only the instance owner can change it.'}
      </p>

      <div className="h-px bg-line my-4.5" />

      <div className="grid grid-cols-[84px_1fr] gap-y-2 text-[12.5px]">
        {member.created_at && (
          <>
            <span className="text-dim">Joined</span>
            <span>{formatJoined(member.created_at)}</span>
          </>
        )}
        <span className="text-dim">Account</span>
        <span className="font-mono text-[11.5px] text-dim break-all">
          {member.user_id}
        </span>
      </div>

      {error && <div className="text-bad text-[13px] mt-4">{error}</div>}

      <Button
        variant="danger"
        className="w-full mt-5"
        onClick={remove}
        disabled={busy}
      >
        {busy ? <Spinner /> : 'Remove from project'}
      </Button>
    </div>
  )
}

function AddPanel({ pid, isOwner, canModerate, net, memberIds, onAdded }) {
  const [directory, setDirectory] = useState([])
  const [query, setQuery] = useState('')
  const [role, setRole] = useState('member')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [token, setToken] = useState('')

  useEffect(() => {
    let live = true
    api
      .listUsers()
      .then((u) => live && setDirectory(u))
      .catch(() => {
        /* the directory is an affordance; typing an address still works */
      })
    return () => {
      live = false
    }
  }, [pid])

  const needle = query.trim().toLowerCase()
  const matches = needle
    ? directory
        .filter(
          (u) =>
            u.email.toLowerCase().includes(needle) ||
            (u.username || '').toLowerCase().includes(needle),
        )
        .slice(0, 6)
    : directory.filter((u) => !memberIds.has(u.user_id)).slice(0, 6)

  const add = async (email) => {
    setBusy(true)
    setError('')
    setToken('')
    try {
      await api.addMember(pid, email, role)
      setQuery('')
      await onAdded()
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  const invite = async () => {
    setBusy(true)
    setError('')
    try {
      const res = await api.createInvite(pid, role)
      setToken(res.invite_token)
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  if (!canModerate) {
    return (
      <div className="p-5 text-dim text-[13px] leading-relaxed">
        Select someone to see their details. Only project admins and the
        instance owner can add or remove people.
      </div>
    )
  }

  return (
    <div className="p-5">
      <h3 className="text-[15px] font-semibold">Add someone</h3>
      <p className="text-dim text-xs leading-relaxed mt-1">
        Pick an account you can already see, or invite a new one.
      </p>

      <label className={`${labelCls} mt-4`} htmlFor="rail-find">
        Account
      </label>
      <input
        id="rail-find"
        className={inputCls}
        type="text"
        value={query}
        placeholder={directory.length ? 'search, or type an email' : 'their email'}
        onChange={(e) => {
          setQuery(e.target.value)
          setError('')
          setToken('')
        }}
      />

      {matches.length > 0 && (
        <ul className="mt-2 border border-line rounded-lg overflow-hidden">
          {matches.map((u) => {
            const already = memberIds.has(u.user_id)
            return (
              <li key={u.user_id} className="border-b border-line last:border-0">
                <button
                  type="button"
                  disabled={already || busy}
                  onClick={() => add(u.email)}
                  className={cx(
                    'w-full flex items-center gap-2.5 text-left px-3 py-2 transition',
                    already
                      ? 'opacity-45 cursor-default'
                      : 'cursor-pointer hover:bg-accent/10',
                  )}
                >
                  <Avatar email={u.email} size={26} />
                  <span className="flex-1 min-w-0">
                    <span className="block text-[13px] truncate">{u.email}</span>
                    {u.username && (
                      <span className="block text-[11px] text-dim truncate">
                        {u.username}
                      </span>
                    )}
                  </span>
                  {already && (
                    <span className="text-[10.5px] text-dim shrink-0">
                      already a member
                    </span>
                  )}
                </button>
              </li>
            )
          })}
        </ul>
      )}

      <label className={`${labelCls} mt-4`} htmlFor="rail-newrole">
        Role
      </label>
      <select
        id="rail-newrole"
        className={inputCls}
        value={role}
        onChange={(e) => setRole(e.target.value)}
      >
        <option value="member">member</option>
        {isOwner && <option value="admin">admin</option>}
      </select>

      <Button
        variant="primary"
        className="w-full mt-4"
        disabled={busy || !query.trim()}
        onClick={() => add(query.trim())}
      >
        {busy ? <Spinner /> : 'Add to project'}
      </Button>

      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}

      <div className="h-px bg-line my-5" />

      {token ? (
        <Handoff token={token} role={role} net={net} />
      ) : (
        <>
          <p className="text-dim text-xs leading-relaxed">
            No account yet? An invite creates one and joins it to this project
            as <span className="text-ink">{role}</span>.
          </p>
          <Button className="w-full mt-2.5" onClick={invite} disabled={busy}>
            Generate an invite
          </Button>
        </>
      )}
    </div>
  )
}

// What to actually send someone. Two separate facts, shown together only
// because this is the moment you need both: the address is a property of the
// deployment, the token is a credential that works at any address.
function Handoff({ token, role, net }) {
  const [copied, setCopied] = useState('')

  const copy = async (what, value) => {
    try {
      await navigator.clipboard.writeText(value)
      setCopied(what)
    } catch {
      /* clipboard blocked; both fields are selectable */
    }
  }

  const address =
    net && !net.loopback_only && net.addresses.length
      ? reachUrl(net.addresses[0], net.port)
      : null

  return (
    <div>
      <h4 className="text-[13.5px] font-semibold">Send them both of these</h4>

      <div className="mt-3.5">
        <div className="flex items-baseline gap-2">
          <span className="w-4 text-accent text-[12px] font-bold">1</span>
          <span className="text-[12.5px]">Where to open Atlas</span>
        </div>
        {address ? (
          <div className="flex items-center gap-2 mt-1.5 ml-6">
            <code className="flex-1 min-w-0 truncate font-mono text-[12.5px] bg-input border border-line rounded-lg px-2.5 py-1.5 select-all">
              {address}
            </code>
            <Button size="sm" onClick={() => copy('url', address)}>
              {copied === 'url' ? 'Copied' : 'Copy'}
            </Button>
          </div>
        ) : (
          <div className="ml-6 mt-1.5 rounded-lg px-3 py-2.5 text-[12px] leading-relaxed bg-warn/[0.12] border border-warn/30 text-[#f4d488]">
            Atlas only accepts connections from this computer, so there is no
            address to send yet. The token stays valid — restart with{' '}
            <span className="font-mono select-all">atlas serve --host 0.0.0.0</span>{' '}
            and this panel will show the address.
          </div>
        )}
      </div>

      <div className="mt-4">
        <div className="flex items-baseline gap-2">
          <span className="w-4 text-accent text-[12px] font-bold">2</span>
          <span className="text-[12.5px]">Their invite token</span>
        </div>
        <div className="flex items-center gap-2 mt-1.5 ml-6">
          <input
            readOnly
            value={token}
            aria-label="Invite token"
            onFocus={(e) => e.target.select()}
            className={`${inputCls} font-mono text-[12px] py-1.5`}
          />
          <Button size="sm" onClick={() => copy('token', token)}>
            {copied === 'token' ? 'Copied' : 'Copy'}
          </Button>
        </div>
      </div>

      <p className="text-dim text-[11.5px] leading-relaxed mt-4 ml-6">
        They open the address, choose{' '}
        <span className="text-ink">Have an invite?</span> and paste the token.
        It creates their account, joins them as{' '}
        <span className="text-ink">{role}</span>, and expires shortly.
      </p>
    </div>
  )
}
