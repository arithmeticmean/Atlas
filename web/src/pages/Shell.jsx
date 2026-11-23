import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react'
import { flushSync } from 'react-dom'
import {
  Archive, Check, ChevronsUpDown, FileText, FolderPlus, LogOut, Menu as MenuIcon, MessageSquarePlus,
  Moon, MoreHorizontal, Pencil, Pin, PinOff, Plug, Settings2, Sun, Trash2, UserCog, Users, X,
} from 'lucide-react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { dayGroup } from '../lib/format.js'
import { useInterval, useLoad } from '../lib/hooks.js'
import { navigate, projectHref } from '../lib/router.js'
import { useTheme } from '../lib/theme.js'
import {
  Button, Contours, cx, ErrorState, IconButton, inputClass, Menu, MenuItem, Modal, Notice, Spinner, TextField, useConfirm, useToast, Wordmark,
} from '../ui/index.jsx'
import Chat from './Chat.jsx'
import Documents from './Documents.jsx'
import Members from './Members.jsx'
import Connectors from './Connectors.jsx'
import ProjectSettings from './ProjectSettings.jsx'
import Account from './Account.jsx'
import SettingsLayout from './Settings.jsx'

const WorkspaceContext = createContext(null)
export const useWorkspace = () => useContext(WorkspaceContext)

export const canManage = (project) => project?.my_role === 'owner' || project?.my_role === 'admin'

export default function Shell({ route }) {
  const { isInstanceAdmin } = useAuth()
  const projects = useLoad(async () => (await api.projects({ limit: 100 })).items, [])
  const [drawer, setDrawer] = useState(false)
  const [creating, setCreating] = useState(false)
  const ready = useLoad(() => api.ready().catch(() => ({ ready: false, unreachable: true })), [])
  useInterval(ready.reload, 8000)

  const list = projects.data
  const routeProject = route.name === 'project' ? list?.find((p) => p.id === route.projectId) : null
  const lastProject = useMemo(() => {
    try {
      return list?.find((p) => p.id === localStorage.getItem('atlas.project')) ?? list?.[0]
    } catch {
      return list?.[0]
    }
  }, [list])

  useEffect(() => {
    if (!list) return
    if (route.name === 'home' && lastProject) navigate(projectHref(lastProject.id), { replace: true })
    if (route.name === 'project' && !routeProject) navigate(lastProject ? projectHref(lastProject.id) : '#/', { replace: true })
  }, [route, list, routeProject, lastProject])

  useEffect(() => {
    if (!routeProject) return
    try {
      localStorage.setItem('atlas.project', routeProject.id)
    } catch {
      // only a convenience
    }
  }, [routeProject])

  // Account and admin pages keep the last project in the sidebar.
  const project = routeProject ?? (route.name === 'project' ? null : lastProject ?? null)

  useEffect(() => setDrawer(false), [route])

  const workspace = useMemo(
    () => ({
      project,
      projects: list,
      setProjects: projects.setData,
      reloadProjects: projects.reload,
      ready: ready.data,
      openCreateProject: () => setCreating(true),
    }),
    [project, list, projects.setData, projects.reload, ready.data],
  )

  return (
    <WorkspaceContext.Provider value={workspace}>
      <ChatsProvider project={project}>
        <div className="flex h-dvh overflow-hidden">
          {drawer && <div className="animate-fade fixed inset-0 z-30 bg-black/40 md:hidden" onClick={() => setDrawer(false)} />}
          <aside
            className={cx(
              'fixed inset-y-0 left-0 z-30 flex w-[272px] flex-col border-r border-line bg-canvas transition-transform md:static md:translate-x-0',
              drawer ? 'translate-x-0' : '-translate-x-full',
            )}
          >
            <Sidebar route={route} onClose={() => setDrawer(false)} />
          </aside>
          <div className="flex min-w-0 flex-1 flex-col bg-surface">
            <div className="flex h-12 items-center gap-2 border-b border-line px-2 md:hidden">
              <IconButton icon={MenuIcon} label="Open menu" onClick={() => setDrawer(true)} />
              <span className="truncate font-medium">{project?.name || 'Atlas'}</span>
            </div>
            <ReadinessBanner ready={ready.data} admin={isInstanceAdmin} />
            <main className="min-h-0 flex-1">
              {projects.loading ? (
                <div className="grid h-full place-items-center text-muted"><Spinner size={22} /></div>
              ) : projects.error ? (
                <ErrorState error={projects.error} onRetry={projects.reload} />
              ) : (
                <Content route={route} />
              )}
            </main>
          </div>
        </div>
        <CreateProject open={creating} onClose={() => setCreating(false)} />
      </ChatsProvider>
    </WorkspaceContext.Provider>
  )
}

function Content({ route }) {
  const { project, projects } = useWorkspace()
  const { isInstanceAdmin } = useAuth()
  if (route.name === 'account') return <Account />
  if (route.name === 'admin') {
    if (!isInstanceAdmin) return <ErrorState error={{ message: 'This page is for instance admins.' }} />
    return <SettingsLayout page={route.page} />
  }
  if (!projects?.length) return <Welcome />
  if (!project) return null
  if (route.page === 'documents') return <Documents key={project.id} />
  if (route.page === 'members') return <Members key={project.id} />
  if (route.page === 'connectors' && canManage(project)) return <Connectors key={project.id} />
  if (route.page === 'settings' && canManage(project)) return <ProjectSettings key={project.id} />
  return <Chat key={project.id} chatId={route.chatId} />
}

function Welcome() {
  const { isInstanceAdmin } = useAuth()
  const { openCreateProject } = useWorkspace()
  return (
    <div className="relative grid h-full place-items-center overflow-hidden px-6">
      <div className="pointer-events-none absolute inset-0 [mask-image:radial-gradient(ellipse_at_center,transparent_24%,black_62%)]">
        <Contours className="absolute left-1/2 top-1/2 w-[1100px] max-w-none -translate-x-1/2 -translate-y-1/2 overflow-visible text-line-strong" rings={24} />
      </div>
      <div className="animate-rise relative max-w-md text-center">
        <h1 className="font-serif text-[38px] leading-tight tracking-tight">Start your first map</h1>
        <p className="mt-2 text-[15px] text-muted">
          {isInstanceAdmin
            ? 'A project holds a set of documents and the people who can ask them questions.'
            : "You aren't in a project yet. Ask an admin to invite you."}
        </p>
        {isInstanceAdmin && (
          <Button variant="primary" size="lg" icon={FolderPlus} className="mt-6" onClick={openCreateProject}>
            Create a project
          </Button>
        )}
      </div>
    </div>
  )
}

function ReadinessBanner({ ready, admin }) {
  if (!ready || ready.ready) return null
  const message = ready.unreachable
    ? "Can't reach the server. Retrying…"
    : ready.reindexing
      ? 'Rebuilding the search index. Uploads and answers resume when it finishes.'
      : 'The AI models aren’t reachable, so uploads and answers are paused.'
  return (
    <Notice
      tone="warn"
      className="rounded-none"
      action={admin && !ready.unreachable && !ready.reindexing ? <a href="#/admin/ai" className="font-medium underline underline-offset-2">Open AI settings</a> : null}
    >
      {message}
    </Notice>
  )
}

function CreateProject({ open, onClose }) {
  const { setProjects } = useWorkspace()
  const toast = useToast()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    try {
      const project = await api.createProject(name.trim())
      // Before navigating, or the new route briefly points at an unknown project.
      flushSync(() => setProjects((all) => [...(all || []), project].sort((a, b) => a.name.localeCompare(b.name))))
      setName('')
      onClose()
      navigate(projectHref(project.id, 'documents'))
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy(false)
    }
  }
  return (
    <Modal open={open} onClose={onClose} title="New project" description="Documents, chats and members are kept separate per project.">
      <form onSubmit={submit} className="space-y-4">
        <TextField label="Name" autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} placeholder="Legal, Engineering, Research…" />
        <div className="flex justify-end gap-2">
          <Button onClick={onClose}>Cancel</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>Create</Button>
        </div>
      </form>
    </Modal>
  )
}

// --- chats, shared by the sidebar and the chat page --------------------------

const ChatsContext = createContext(null)
export const useChats = () => useContext(ChatsContext)

function ChatsProvider({ project, children }) {
  const pid = project?.id
  const chats = useLoad(async () => (pid ? (await api.chats(pid, { limit: 100 })).items : []), [pid])
  const { setData } = chats
  const upsert = useCallback(
    (chat) => setData((all) => [chat, ...(all || []).filter((c) => c.id !== chat.id)]),
    [setData],
  )
  const remove = useCallback((id) => setData((all) => (all || []).filter((c) => c.id !== id)), [setData])
  const value = useMemo(() => ({ chats: chats.data, loading: chats.loading, upsert, remove }), [chats.data, chats.loading, upsert, remove])
  return <ChatsContext.Provider value={value}>{children}</ChatsContext.Provider>
}

// --- sidebar -----------------------------------------------------------------

function Sidebar({ route, onClose }) {
  const { project } = useWorkspace()
  const page = route.name === 'project' ? route.page : null
  return (
    <>
      <div className="flex h-14 items-center justify-between px-4">
        <a href="#/" className="rounded-md"><Wordmark /></a>
        <IconButton icon={X} label="Close menu" onClick={onClose} className="md:hidden" />
      </div>
      <div className="px-3"><ProjectSwitcher /></div>
      {project && (
        <>
          <div className="px-3 pt-3">
            <a
              href={projectHref(project.id)}
              className="flex h-9 items-center gap-2 rounded-lg bg-accent px-3 font-medium text-on-accent shadow-sm transition hover:brightness-[1.07]"
              onClick={() => window.dispatchEvent(new Event('atlas:new-chat'))}
            >
              <MessageSquarePlus size={16} aria-hidden="true" /> New chat
            </a>
          </div>
          <nav className="space-y-0.5 px-3 pt-3" aria-label="Project">
            <NavLink href={projectHref(project.id, 'documents')} icon={FileText} active={page === 'documents'}>Documents</NavLink>
            <NavLink href={projectHref(project.id, 'members')} icon={Users} active={page === 'members'}>Members</NavLink>
            {canManage(project) && (
              <>
                <NavLink href={projectHref(project.id, 'connectors')} icon={Plug} active={page === 'connectors'}>Connectors</NavLink>
                <NavLink href={projectHref(project.id, 'settings')} icon={Settings2} active={page === 'settings'}>Project settings</NavLink>
              </>
            )}
          </nav>
        </>
      )}
      <div className="mt-3 min-h-0 flex-1 overflow-y-auto px-3 pb-2">{project && <ChatList activeId={page === 'chat' ? route.chatId : null} />}</div>
      <UserMenu />
    </>
  )
}

function NavLink({ href, icon: Icon, active, children }) {
  return (
    <a
      href={href}
      aria-current={active ? 'page' : undefined}
      className={cx(
        'flex h-8 items-center gap-2.5 rounded-lg px-2.5 text-[13.5px] transition',
        active ? 'bg-raised font-medium text-ink' : 'text-muted hover:bg-raised hover:text-ink',
      )}
    >
      <Icon size={15} aria-hidden="true" /> {children}
    </a>
  )
}

function ProjectSwitcher() {
  const { project, projects, openCreateProject } = useWorkspace()
  const { isInstanceAdmin } = useAuth()
  if (!projects?.length && !isInstanceAdmin) return null
  return (
    <Menu
      align="left"
      trigger={({ toggle, open }) => (
        <button
          type="button"
          aria-expanded={open}
          onClick={toggle}
          className="flex h-11 w-full items-center gap-2.5 rounded-lg border border-line bg-surface px-2.5 text-left transition hover:border-line-strong"
        >
          <span className="grid size-6 shrink-0 place-items-center rounded-md bg-accent-soft font-serif text-[14px] text-accent">
            {(project?.name || '+')[0].toUpperCase()}
          </span>
          <span className="min-w-0 flex-1 truncate font-medium">{project?.name || 'Choose a project'}</span>
          <ChevronsUpDown size={14} className="shrink-0 text-faint" aria-hidden="true" />
        </button>
      )}
    >
      {(close) => (
        <div className="w-[238px]">
          <div className="max-h-64 overflow-y-auto">
            {projects?.map((p) => (
              <MenuItem key={p.id} icon={p.id === project?.id ? Check : undefined} onClick={() => { close(); navigate(projectHref(p.id)) }}>
                {p.name}
              </MenuItem>
            ))}
          </div>
          {isInstanceAdmin && (
            <>
              {projects?.length > 0 && <div className="my-1 border-t border-line" />}
              <MenuItem icon={FolderPlus} onClick={() => { close(); openCreateProject() }}>New project</MenuItem>
            </>
          )}
        </div>
      )}
    </Menu>
  )
}

const GROUPS = ['Today', 'Yesterday', 'Previous 7 days', 'Previous 30 days', 'Older']

function ChatList({ activeId }) {
  const { chats, loading } = useChats()
  if (loading) {
    return <div className="space-y-2 pt-2">{[0, 1, 2].map((i) => <div key={i} className="skeleton h-6" />)}</div>
  }
  if (!chats?.length) return <p className="px-2.5 pt-2 text-[13px] text-faint">Your chats will appear here.</p>
  const pinned = chats.filter((c) => c.pinned)
  const rest = chats.filter((c) => !c.pinned)
  const section = (label, items) =>
    items.length > 0 && (
      <div key={label} className="pt-2.5">
        <h2 className="px-2.5 pb-1 text-[11.5px] font-medium text-faint">{label}</h2>
        {items.map((chat) => <ChatRow key={chat.id} chat={chat} active={chat.id === activeId} />)}
      </div>
    )
  return (
    <>
      {section('Pinned', pinned)}
      {GROUPS.map((g) => section(g, rest.filter((c) => dayGroup(c.last_message_at || c.created_at) === g)))}
    </>
  )
}

function ChatRow({ chat, active }) {
  const { project } = useWorkspace()
  const { upsert, remove } = useChats()
  const toast = useToast()
  const confirm = useConfirm()
  const [renaming, setRenaming] = useState(false)
  const [title, setTitle] = useState('')

  const update = async (body) => {
    try {
      return await api.updateChat(project.id, chat.id, body)
    } catch (e) {
      toast.error(e)
      return null
    }
  }
  const rename = async () => {
    setRenaming(false)
    const next = title.trim()
    if (next && next !== chat.title) {
      const saved = await update({ title: next })
      if (saved) upsert(saved)
    }
  }
  const archive = async () => {
    if (await update({ archived: true })) {
      remove(chat.id)
      if (active) navigate(projectHref(project.id))
      toast.ok('Chat archived')
    }
  }
  const destroy = async () => {
    const yes = await confirm({ title: 'Delete this chat?', message: `“${chat.title || 'New chat'}” will be gone for good.`, action: 'Delete', danger: true })
    if (!yes) return
    try {
      await api.deleteChat(project.id, chat.id)
      remove(chat.id)
      if (active) navigate(projectHref(project.id))
    } catch (e) {
      toast.error(e)
    }
  }

  if (renaming) {
    return (
      <input
        autoFocus
        aria-label="Chat title"
        className={cx(inputClass, 'h-8 text-[13.5px]')}
        value={title}
        maxLength={200}
        onChange={(e) => setTitle(e.target.value)}
        onBlur={rename}
        onKeyDown={(e) => {
          if (e.key === 'Enter') rename()
          if (e.key === 'Escape') setRenaming(false)
        }}
      />
    )
  }
  return (
    <div className={cx('group relative flex items-center rounded-lg transition', active ? 'bg-raised' : 'hover:bg-raised')}>
      <a
        href={projectHref(project.id, 'chat', chat.id)}
        aria-current={active ? 'page' : undefined}
        className={cx('min-w-0 flex-1 truncate py-1.5 pl-2.5 pr-8 text-[13.5px]', active ? 'font-medium text-ink' : 'text-muted group-hover:text-ink')}
      >
        {chat.title || 'New chat'}
      </a>
      <Menu
        className="absolute right-0.5"
        trigger={({ toggle, open }) => (
          <IconButton
            icon={MoreHorizontal}
            label={`Options for ${chat.title || 'chat'}`}
            onClick={toggle}
            className={cx('size-7 focus:opacity-100 group-hover:opacity-100 max-md:opacity-100', open || active ? 'opacity-100' : 'opacity-0')}
          />
        )}
      >
        {(close) => (
          <>
            <MenuItem icon={Pencil} onClick={() => { close(); setTitle(chat.title || ''); setRenaming(true) }}>Rename</MenuItem>
            <MenuItem icon={chat.pinned ? PinOff : Pin} onClick={async () => { close(); const saved = await update({ pinned: !chat.pinned }); if (saved) upsert(saved) }}>
              {chat.pinned ? 'Unpin' : 'Pin'}
            </MenuItem>
            <MenuItem icon={Archive} onClick={() => { close(); archive() }}>Archive</MenuItem>
            <MenuItem icon={Trash2} danger onClick={() => { close(); destroy() }}>Delete</MenuItem>
          </>
        )}
      </Menu>
    </div>
  )
}

function UserMenu() {
  const { user, signOut, isInstanceAdmin } = useAuth()
  const { theme, toggle } = useTheme()
  const { ready } = useWorkspace()
  const dot = !ready ? 'bg-faint' : ready.ready ? 'bg-ok' : 'bg-warn'
  return (
    <div className="border-t border-line p-2">
      <Menu
        side="up"
        align="left"
        trigger={({ toggle: toggleMenu, open }) => (
          <button type="button" aria-expanded={open} onClick={toggleMenu} className="flex w-full items-center gap-2.5 rounded-lg p-1.5 text-left transition hover:bg-raised">
            <span className="relative grid size-8 shrink-0 place-items-center rounded-full bg-raised font-medium uppercase">
              {user?.username?.[0]}
              <span title={ready?.ready ? 'All systems ready' : 'Not ready'} className={cx('absolute -bottom-px -right-px size-2.5 rounded-full border-2 border-canvas', dot)} />
            </span>
            <span className="min-w-0 flex-1">
              <span className="block truncate text-[13.5px] font-medium leading-tight">{user?.username}</span>
              <span className="block truncate text-xs capitalize leading-tight text-faint">{user?.role}</span>
            </span>
            <ChevronsUpDown size={14} className="shrink-0 text-faint" aria-hidden="true" />
          </button>
        )}
      >
        {(close) => {
          const go = (href) => () => { close(); navigate(href) }
          return (
            <div className="w-[238px]">
              <div className="truncate px-2.5 py-1.5 text-xs text-faint">{user?.email}</div>
              <MenuItem icon={UserCog} onClick={go('#/account')}>Account</MenuItem>
              <MenuItem icon={theme === 'dark' ? Sun : Moon} onClick={toggle}>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</MenuItem>
              {isInstanceAdmin && (
                <>
                  <div className="my-1 border-t border-line" />
                  <MenuItem icon={Settings2} onClick={go('#/admin/ai')}>Settings</MenuItem>
                </>
              )}
              <div className="my-1 border-t border-line" />
              <MenuItem icon={LogOut} onClick={() => { close(); signOut() }}>Sign out</MenuItem>
            </div>
          )
        }}
      </Menu>
    </div>
  )
}
