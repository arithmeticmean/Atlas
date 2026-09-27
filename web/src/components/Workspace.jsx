import { useEffect, useState } from 'react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { projectPath } from '../lib/router.js'
import { Badge, Brand, Button, Card, Spinner, cx, inputCls } from './ui.jsx'
import Chat from './Chat.jsx'
import Search from './Search.jsx'
import Documents from './Documents.jsx'
import Connectors from './Connectors.jsx'
import Members from './Members.jsx'
import Health from './Health.jsx'

const BASE_NAV = [
  { id: 'chat', label: 'Chat', component: Chat },
  { id: 'search', label: 'Search', component: Search },
  { id: 'documents', label: 'Documents', component: Documents },
]
const MOD_NAV = [
  { id: 'connectors', label: 'Connectors', component: Connectors },
  { id: 'members', label: 'Members', component: Members },
]
const HEALTH_NAV = { id: 'health', label: 'Health', component: Health }
const MOD_PAGES = new Set(['connectors', 'members'])

// The authenticated shell. Selected project + page are derived from the route
// (#/p/<projectId>/<page>); the sidebar and nav navigate() rather than holding
// their own state, so URLs stay in sync and refresh is lossless.
export default function Workspace({ route, navigate }) {
  const { user, signOut } = useAuth()
  const [projects, setProjects] = useState(null) // null = loading
  const [ready, setReady] = useState(null)
  // The chat's source rail. Lives here rather than in Chat so the toggle can
  // sit in the page header beside the title, and so collapsing it survives
  // navigating away from chat and back.
  const [railOpen, setRailOpen] = useState(true)

  const reloadProjects = async () => {
    const projs = await api.listProjects()
    setProjects(projs)
    return projs
  }

  useEffect(() => { reloadProjects().catch(() => setProjects([])) }, [])

  useEffect(() => {
    let alive = true
    const poll = async () => {
      try {
        const r = await api.ready()
        if (alive) setReady(r)
      } catch {
        if (alive) setReady({ ready: false, unreachable: true })
      }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => { alive = false; clearInterval(id) }
  }, [])

  const routeProjectId = route.name === 'project' ? route.projectId : null
  const routePage =
    route.name === 'project'
      ? route.page
      : route.name === 'health'
        ? 'health'
        : 'chat'

  const selected =
    (projects || []).find((p) => p.id === routeProjectId) ||
    (projects || [])[0] ||
    null

  const canModerate =
    selected && (selected.role === 'owner' || selected.role === 'admin')
  const nav = canModerate ? [...BASE_NAV, ...MOD_NAV] : [...BASE_NAV]
  const navAll = [...nav, HEALTH_NAV]

  const pageId =
    navAll.some((n) => n.id === routePage) &&
    !(MOD_PAGES.has(routePage) && !canModerate)
      ? routePage
      : 'chat'

  useEffect(() => {
    if (!projects || !selected) return
    if (routeProjectId !== selected.id || routePage !== pageId) {
      navigate(projectPath(selected.id, pageId))
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [projects, selected, routeProjectId, routePage, pageId])

  const active = navAll.find((n) => n.id === pageId) || HEALTH_NAV
  const Page = active.component

  const showChat = active.id === 'chat' && projects && selected
  // Members uses the same roster-plus-rail layout as chat, so it needs the
  // full height too rather than the padded, centred scroll container.
  const showMembers = active.id === 'members' && projects && selected

  return (
    <div className="flex h-screen overflow-hidden">
      <aside className="w-[216px] shrink-0 flex flex-col gap-1 py-[18px] px-3 border-r border-line bg-[linear-gradient(180deg,rgb(255_255_255_/_0.02),transparent),var(--color-elev)]">
        <Brand className="block text-[19px] font-extrabold tracking-tight px-2.5 pt-1.5 pb-4" />

        <ProjectSwitcher
          projects={projects}
          selectedId={selected?.id || ''}
          onSelect={(id) => navigate(projectPath(id, 'chat'))}
          isOwner={user?.role === 'owner'}
          onProjectsChanged={reloadProjects}
        />

        <div className="flex flex-col gap-0.5">
          {navAll.map((n) => (
            <button
              key={n.id}
              className={navCls(n.id === pageId)}
              onClick={() =>
                navigate(
                  n.id === 'health' && !selected
                    ? '#/health'
                    : projectPath(selected?.id || '', n.id),
                )
              }
              disabled={!selected && n.id !== 'health'}
            >
              {n.label}
            </button>
          ))}
        </div>

        <div className="flex-1" />
        <div className="px-3 py-2">
          <ReadinessDot ready={ready} />
        </div>
        <div className="border-t border-line pt-2.5 px-2.5 mt-2 flex flex-col gap-1.5">
          <div className="text-xs font-mono truncate">{user?.email}</div>
          <div className="flex items-center justify-between">
            <Badge>{user?.role}</Badge>
            <Button size="sm" onClick={signOut}>Sign out</Button>
          </div>
        </div>
      </aside>

      <main className="flex-1 min-w-0 flex flex-col">
        <div className="h-[54px] flex items-center gap-3 px-[22px] border-b border-line bg-[rgb(10_12_18_/_0.4)] backdrop-blur-md">
          <h1 className="text-[15px] font-semibold tracking-tight">{active.label}</h1>
          {selected && (
            <span className="text-xs text-dim bg-elev-2 border border-line rounded-full px-2.5 py-[3px]">
              {selected.name}
            </span>
          )}
          {showChat && (
            <>
              <div className="flex-1" />
              <button
                type="button"
                onClick={() => setRailOpen((v) => !v)}
                aria-expanded={railOpen}
                className="inline-flex items-center gap-2 text-[12.5px] text-dim bg-elev-2 border border-line-2 rounded-lg px-2.5 py-1.5 hover:border-accent hover:text-ink transition cursor-pointer"
              >
                <PanelIcon />
                {railOpen ? 'Hide sources' : 'Show sources'}
              </button>
            </>
          )}
        </div>

        {ready && !ready.ready && (
          <div
            className={cx(
              'px-[22px] py-[11px] text-[13px] border-b',
              ready.unreachable
                ? 'bg-bad/15 text-[#fecdd3] border-bad/30'
                : 'bg-accent/15 text-[#cbd1fb] border-accent/25',
            )}
          >
            {ready.unreachable
              ? 'Backend unreachable — is the API running on :8000?'
              : ready.reindexing
                ? 'Reindexing embeddings… uploads, sync and answers are paused (503) until this finishes.'
                : 'Instance not ready yet.'}
          </div>
        )}

        {showChat ? (
          // Chat owns the full height: it scrolls its own transcript and pins
          // the composer to the bottom (Claude-style).
          <Chat
            projectId={selected.id}
            project={selected}
            railOpen={railOpen}
            onOpenDocuments={() =>
              navigate(projectPath(selected.id, 'documents'))
            }
          />
        ) : showMembers ? (
          <Members project={selected} />
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto">
            <div className="p-6 max-w-[900px] w-full mx-auto">
              {active.id === 'health' ? (
                <Health ready={ready} />
              ) : projects === null ? (
                <Card className="text-dim">Loading…</Card>
              ) : !selected ? (
                <NoProject isOwner={user?.role === 'owner'} />
              ) : (
                <Page projectId={selected.id} project={selected} ready={ready} />
              )}
            </div>
          </div>
        )}
      </main>
    </div>
  )
}

function PanelIcon() {
  return (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor"
      strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
      <rect x="3" y="4" width="18" height="16" rx="2" />
      <path d="M15 4v16" />
    </svg>
  )
}

function navCls(active) {
  return cx(
    'relative w-full text-left rounded-lg px-3 py-2.5 cursor-pointer transition',
    'disabled:opacity-40 disabled:cursor-default',
    active
      ? "bg-accent/15 text-[#c7cdfb] font-semibold before:content-[''] before:absolute before:left-[3px] before:top-[22%] before:bottom-[22%] before:w-[3px] before:rounded before:bg-[linear-gradient(180deg,var(--color-accent),var(--color-accent-2))]"
      : 'text-dim hover:bg-elev-2 hover:text-ink',
  )
}

function ProjectSwitcher({ projects, selectedId, onSelect, isOwner, onProjectsChanged }) {
  const [creating, setCreating] = useState(false)
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const create = async () => {
    setBusy(true); setError('')
    try {
      const p = await api.createProject(name.trim())
      setName(''); setCreating(false)
      await onProjectsChanged()
      onSelect(p.id)
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  return (
    <div className="px-2.5 pb-3.5 mb-2.5 border-b border-line">
      <label className="block text-[11px] uppercase tracking-wide text-faint mb-1.5">
        Project
      </label>
      <select
        className={inputCls}
        value={selectedId}
        onChange={(e) => onSelect(e.target.value)}
        disabled={!projects || projects.length === 0}
      >
        {(!projects || projects.length === 0) && <option value="">— none —</option>}
        {(projects || []).map((p) => (
          <option key={p.id} value={p.id}>{p.name}</option>
        ))}
      </select>

      {isOwner && (
        creating ? (
          <div className="mt-3">
            <input className={inputCls} value={name} placeholder="New project name" autoFocus
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && name.trim() && create()} />
            {error && <div className="text-bad text-xs mt-2">{error}</div>}
            <div className="flex items-center gap-2.5 mt-3">
              <Button variant="primary" size="sm" onClick={create} disabled={busy || !name.trim()}>
                {busy ? <Spinner /> : 'Create'}
              </Button>
              <Button size="sm" onClick={() => setCreating(false)}>Cancel</Button>
            </div>
          </div>
        ) : (
          <Button variant="ghost" size="sm" className="mt-3" onClick={() => setCreating(true)}>
            + New project
          </Button>
        )
      )}
    </div>
  )
}

function NoProject({ isOwner }) {
  return (
    <Card className="text-dim">
      {isOwner
        ? 'No projects yet. Create your first one from the sidebar to start ingesting and asking questions.'
        : "You're not a member of any project yet. Ask an owner or a project admin to invite you."}
    </Card>
  )
}

function ReadinessDot({ ready }) {
  let tone = 'dim'
  let text = 'checking…'
  if (ready) {
    if (ready.unreachable) { tone = 'err'; text = 'offline' }
    else if (ready.ready) { tone = 'ok'; text = 'ready' }
    else { tone = 'warn'; text = ready.reindexing ? 'reindexing' : 'starting' }
  }
  return <Badge tone={tone}>{text}</Badge>
}
