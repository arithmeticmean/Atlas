import { useEffect, useMemo, useState } from 'react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { Avatar } from './Avatar.jsx'
import MemberRail from './MemberRail.jsx'
import { Badge, Button, Spinner, cx } from './ui.jsx'

// Project membership, laid out like the chat: the roster keeps the left, and
// whatever you are doing with it happens in a rail on the right. Selecting a
// person shows their detail; with nobody selected the rail is the add flow, so
// the primary action is always on screen without a popover or a modal.
export default function Members({ project }) {
  const pid = project.id
  const isOwner = project.role === 'owner'
  const canModerate = isOwner || project.role === 'admin'
  const { user } = useAuth()

  const [members, setMembers] = useState(null) // null = loading
  const [selectedId, setSelectedId] = useState(null)
  const [net, setNet] = useState(null)
  const [error, setError] = useState('')

  const refresh = async () => {
    try {
      setMembers(await api.listMembers(pid))
      setError('')
    } catch (e) {
      setError(e.message)
    }
  }

  useEffect(() => {
    setMembers(null)
    setSelectedId(null)
    refresh()
  }, [pid])

  useEffect(() => {
    let live = true
    api
      .network()
      .then((n) => live && setNet(n))
      .catch(() => {
        /* reachability is informational; the panel copes without it */
      })
    return () => {
      live = false
    }
  }, [])

  const selected = useMemo(
    () => (members || []).find((m) => m.user_id === selectedId) || null,
    [members, selectedId],
  )
  const memberIds = useMemo(
    () => new Set((members || []).map((m) => m.user_id)),
    [members],
  )

  return (
    <div className="flex-1 min-h-0 flex">
      <div className="flex-1 min-w-0 flex flex-col">
        <div className="flex-1 min-h-0 overflow-y-auto">
          <div className="px-6 py-6 max-w-[720px]">
            <div className="flex items-center gap-3">
              <h2 className="text-[20px] font-semibold tracking-tight">
                {members === null
                  ? 'People'
                  : `${members.length} ${members.length === 1 ? 'person' : 'people'}`}
              </h2>
              <div className="flex-1" />
              {canModerate && (
                <Button
                  variant={selectedId === null ? 'primary' : 'default'}
                  size="sm"
                  onClick={() => setSelectedId(null)}
                >
                  Add someone
                </Button>
              )}
            </div>

            {error && <div className="text-bad text-[13px] mt-3">{error}</div>}

            {members === null ? (
              <div className="flex items-center gap-2 text-dim text-[13px] mt-5">
                <Spinner /> loading members…
              </div>
            ) : members.length === 0 ? (
              <p className="text-dim text-[13px] mt-4 leading-relaxed">
                Nobody has been added to this project yet. The instance owner
                can always reach every project, which is why they are not
                listed here.
              </p>
            ) : (
              <div className="mt-4 flex flex-col gap-1">
                {members.map((m) => {
                  const on = m.user_id === selectedId
                  return (
                    <button
                      key={m.user_id}
                      type="button"
                      aria-current={on ? 'true' : undefined}
                      onClick={() => setSelectedId(m.user_id)}
                      className={cx(
                        'w-full flex items-center gap-3 px-3 py-2.5 rounded-xl',
                        'text-left transition cursor-pointer border',
                        on
                          ? 'bg-accent/10 border-accent/40'
                          : 'bg-transparent border-transparent hover:bg-white/[0.03]',
                      )}
                    >
                      <Avatar email={m.email || m.user_id} size={30} />
                      <span className="flex-1 min-w-0">
                        <span className="flex items-center gap-2">
                          <span className="text-[13.5px] truncate">
                            {m.email || 'unknown'}
                          </span>
                          {m.user_id === user?.user_id && (
                            <span className="text-[10px] uppercase tracking-wide text-faint border border-line rounded px-1.5 py-px shrink-0">
                              you
                            </span>
                          )}
                        </span>
                        {m.username && (
                          <span className="block text-[11.5px] text-dim truncate mt-0.5">
                            {m.username}
                          </span>
                        )}
                      </span>
                      <Badge tone={m.role === 'admin' ? 'ok' : 'dim'}>
                        {m.role}
                      </Badge>
                    </button>
                  )
                })}
              </div>
            )}
          </div>
        </div>

        <div className="shrink-0 border-t border-line px-6 py-3 flex items-center gap-2.5">
          <span
            className={cx(
              'w-1.5 h-1.5 rounded-full shrink-0',
              net && !net.loopback_only ? 'bg-ok' : 'bg-warn',
            )}
          />
          {net === null ? (
            <span className="text-[11.5px] text-dim">checking reachability…</span>
          ) : net.loopback_only ? (
            <span className="text-[11.5px] text-dim">
              This device only — others cannot reach this instance yet
            </span>
          ) : net.addresses.length ? (
            <>
              <span className="text-[11.5px] text-dim">Reachable at</span>
              <span className="font-mono text-[11.5px] text-[#b9c2d2] select-all">
                {net.addresses[0]}:{net.port}
              </span>
            </>
          ) : (
            <span className="text-[11.5px] text-dim">
              Bound to {net.bound_host}:{net.port}
            </span>
          )}
        </div>
      </div>

      <MemberRail
        pid={pid}
        selected={selected}
        canModerate={canModerate}
        isOwner={isOwner}
        isSelf={selected?.user_id === user?.user_id}
        net={net}
        memberIds={memberIds}
        onChanged={refresh}
        onCleared={() => setSelectedId(null)}
      />
    </div>
  )
}
