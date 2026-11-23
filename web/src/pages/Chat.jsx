import { memo, useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AlertTriangle, ArrowDown, ArrowUp, BookOpen, Check, Copy, Download, FileText, RefreshCw, Square, ThumbsDown, ThumbsUp, X,
} from 'lucide-react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { navigate, projectHref } from '../lib/router.js'
import { Button, cx, IconButton, Logo, Spinner, useToast } from '../ui/index.jsx'
import { useChats, useWorkspace } from './Shell.jsx'

const PAGE_SIZE = 40

export default function Chat({ chatId }) {
  const { project, ready } = useWorkspace()
  const { chats, upsert } = useChats()
  const toast = useToast()
  const pid = project.id
  const [messages, setMessages] = useState([])
  const [loading, setLoading] = useState(Boolean(chatId))
  const [olderCursor, setOlderCursor] = useState(null)
  const [streaming, setStreaming] = useState(false)
  const [sources, setSources] = useState(null)
  const [draft, setDraft] = useState('')
  const [atBottom, setAtBottom] = useState(true)
  const scroller = useRef(null)
  const abort = useRef(null)
  const openChat = useRef(null) // the chat this view already holds
  const pending = useRef('')
  const frame = useRef(0)

  const chat = chats?.find((c) => c.id === chatId)
  const canSend = ready?.ready !== false

  const stop = useCallback(() => abort.current?.abort(), [])

  useEffect(() => {
    if (chatId === openChat.current) return undefined
    stop()
    openChat.current = chatId
    setSources(null)
    setOlderCursor(null)
    if (!chatId) {
      setMessages([])
      setLoading(false)
      return undefined
    }
    let live = true
    setLoading(true)
    api.messages(pid, chatId, { limit: PAGE_SIZE }).then(
      (page) => {
        if (!live) return
        setMessages([...page.items].reverse())
        setOlderCursor(page.next_cursor)
        setLoading(false)
        requestAnimationFrame(() => scrollToEnd('auto'))
      },
      (e) => {
        if (!live) return
        toast.error(e)
        openChat.current = null
        navigate(projectHref(pid), { replace: true })
      },
    )
    return () => { live = false }
  }, [chatId, pid, stop, toast])

  useEffect(() => stop, [stop])

  // "New chat" while already on the empty route should still clear things.
  useEffect(() => {
    const reset = () => {
      stop()
      setDraft('')
      setSources(null)
      if (!chatId) setMessages([])
    }
    window.addEventListener('atlas:new-chat', reset)
    return () => window.removeEventListener('atlas:new-chat', reset)
  }, [chatId, stop])

  const scrollToEnd = (behavior = 'smooth') => {
    const el = scroller.current
    if (el) el.scrollTo({ top: el.scrollHeight, behavior })
  }

  useLayoutEffect(() => {
    if (atBottom && scroller.current) scroller.current.scrollTop = scroller.current.scrollHeight
  }, [messages, atBottom])

  const onScroll = () => {
    const el = scroller.current
    setAtBottom(el.scrollHeight - el.scrollTop - el.clientHeight < 80)
  }

  const patchMessage = (id, update) =>
    setMessages((all) => all.map((m) => (m.id === id ? { ...m, ...update(m) } : m)))

  /** Apply the server's event stream to the message list. */
  const consume = (run) => async () => {
    const controller = new AbortController()
    abort.current = controller
    setStreaming(true)
    setAtBottom(true)
    let answerId = null
    const flush = () => {
      frame.current = 0
      if (!pending.current || !answerId) return
      const text = pending.current
      pending.current = ''
      patchMessage(answerId, (m) => ({ content: m.content + text }))
    }
    const onEvent = (name, data) => {
      if (name === 'message.created') {
        answerId = data.assistant_message.id
        setMessages((all) => {
          const rest = all.filter(
            (m) => !m.temporary && m.id !== data.user_message.id && m.id !== answerId,
          )
          return [...rest, data.user_message, data.assistant_message]
        })
      } else if (name === 'retrieval') {
        patchMessage(answerId, () => ({ citations: data.citations, rewritten_query: data.rewritten_query }))
      } else if (name === 'token') {
        pending.current += data.delta
        frame.current ||= requestAnimationFrame(flush)
      } else if (name === 'message.completed') {
        cancelAnimationFrame(frame.current)
        pending.current = ''
        frame.current = 0
        patchMessage(answerId, () => data.message)
        // The answer is done. The title may still arrive on this stream, but
        // it must not hold up the next message or be cancelled by leaving.
        abort.current = null
        setStreaming(false)
      } else if (name === 'chat.updated') {
        upsert(data.chat)
      } else if (name === 'error') {
        flush()
        patchMessage(answerId, () => ({ status: 'failed', error: data }))
      }
    }
    try {
      await run(onEvent, controller.signal)
    } catch (e) {
      flush()
      if (e.name === 'AbortError') {
        if (answerId) patchMessage(answerId, () => ({ status: 'stopped' }))
      } else if (answerId) {
        patchMessage(answerId, () => ({ status: 'failed', error: { message: 'The connection was lost.' } }))
      } else {
        setMessages((all) => all.filter((m) => !m.temporary))
        toast.error(e)
        return false
      }
    } finally {
      if (abort.current === controller) {
        abort.current = null
        setStreaming(false)
      }
    }
    return true
  }

  const send = async (text) => {
    const content = text.trim()
    if (!content || streaming) return
    setDraft('')
    let id = chatId
    const temporary = { id: `temp-${Date.now()}`, role: 'user', content, status: 'complete', citations: [], temporary: true }
    setMessages((all) => [...all, temporary])
    if (!id) {
      try {
        const created = await api.createChat(pid)
        id = created.id
        openChat.current = id
        upsert(created)
        navigate(projectHref(pid, 'chat', id), { replace: true })
      } catch (e) {
        setMessages((all) => all.filter((m) => !m.temporary))
        setDraft(content)
        toast.error(e)
        return
      }
    }
    const sent = await consume((onEvent, signal) =>
      api.sendMessage(pid, id, { content, client_message_id: crypto.randomUUID?.() }, onEvent, signal),
    )()
    if (!sent) setDraft(content)
  }

  const regenerate = async (message) => {
    patchMessage(message.id, () => ({ content: '', status: 'streaming', citations: [], feedback: null, error: null }))
    const started = await consume((onEvent, signal) =>
      api.regenerate(pid, chatId, message.id, onEvent, signal),
    )()
    if (!started) patchMessage(message.id, () => message)
  }

  const rate = async (message, rating) => {
    const clearing = message.feedback?.rating === rating
    patchMessage(message.id, () => ({ feedback: clearing ? null : { rating } }))
    try {
      if (clearing) await api.clearFeedback(pid, chatId, message.id)
      else await api.setFeedback(pid, chatId, message.id, rating)
    } catch (e) {
      patchMessage(message.id, () => ({ feedback: message.feedback }))
      toast.error(e)
    }
  }

  const loadOlder = async () => {
    const el = scroller.current
    const before = el.scrollHeight
    try {
      const page = await api.messages(pid, chatId, { limit: PAGE_SIZE, before: olderCursor })
      setAtBottom(false)
      setMessages((all) => [...[...page.items].reverse(), ...all])
      setOlderCursor(page.next_cursor)
      requestAnimationFrame(() => { el.scrollTop = el.scrollHeight - before })
    } catch (e) {
      toast.error(e)
    }
  }

  const empty = !loading && messages.length === 0
  const last = messages[messages.length - 1]

  return (
    <div className="flex h-full">
      <div className="relative flex min-w-0 flex-1 flex-col">
        {chatId && chat && (
          <div className="hidden h-12 shrink-0 items-center justify-between gap-3 border-b border-line px-5 md:flex">
            <h1 className="truncate font-medium">{chat.title || 'New chat'}</h1>
            <IconButton icon={Download} label="Export as Markdown" onClick={() => api.exportChat(pid, chat).catch(toast.error)} />
          </div>
        )}
        {empty ? (
          <div className="flex flex-1 flex-col items-center justify-center overflow-y-auto px-4 pb-6">
            <Welcome project={project} onPick={setDraft} />
            <div className="mt-7 w-full max-w-[720px]">
              <Composer value={draft} onChange={setDraft} onSend={send} streaming={false} disabled={!canSend} autoFocus />
            </div>
          </div>
        ) : (
          <>
            <div ref={scroller} onScroll={onScroll} className="min-h-0 flex-1 overflow-y-auto">
              <div className="mx-auto max-w-[760px] space-y-7 px-4 py-7 sm:px-6">
                {loading ? <TranscriptSkeleton /> : (
                  <>
                    {olderCursor && (
                      <div className="text-center"><Button size="sm" variant="ghost" onClick={loadOlder}>Load earlier messages</Button></div>
                    )}
                    {messages.map((message) =>
                      message.role === 'user' ? (
                        <UserTurn key={message.id} message={message} />
                      ) : (
                        <AssistantTurn
                          key={message.id}
                          message={message}
                          isLast={message === last}
                          busy={streaming}
                          onSources={(focus) => setSources({ message, focus })}
                          onRegenerate={() => regenerate(message)}
                          onRate={(rating) => rate(message, rating)}
                        />
                      ),
                    )}
                  </>
                )}
              </div>
            </div>
            {!atBottom && (
              <button
                type="button"
                aria-label="Scroll to latest"
                onClick={() => { setAtBottom(true); scrollToEnd() }}
                className="animate-fade absolute bottom-28 left-1/2 grid size-9 -translate-x-1/2 place-items-center rounded-full border border-line bg-surface text-muted shadow-float hover:text-ink"
              >
                <ArrowDown size={16} />
              </button>
            )}
            <div className="mx-auto w-full max-w-[760px] px-4 pb-4 sm:px-6">
              <Composer value={draft} onChange={setDraft} onSend={send} onStop={stop} streaming={streaming} disabled={!canSend} />
              <p className="mt-1.5 text-center text-[11.5px] text-faint">Numbered sources come from your documents. Anything without one is general knowledge.</p>
            </div>
          </>
        )}
      </div>
      {sources && <SourcesPanel {...sources} pid={pid} onClose={() => setSources(null)} />}
    </div>
  )
}

function Welcome({ project, onPick }) {
  const { user } = useAuth()
  const ideas = ['Summarize the key points', 'What decisions were made?', 'List the deadlines mentioned']
  return (
    <div className="animate-rise text-center">
      <Logo size={40} className="mx-auto mb-4 text-muted" />
      <h1 className="font-serif text-[34px] leading-tight tracking-tight">
        What should we find, {user?.username}?
      </h1>
      <p className="mt-1.5 text-muted">
        Chat about anything. Atlas draws on the documents in <span className="font-medium text-ink">{project.name}</span>.{' '}
        <a href={projectHref(project.id, 'documents')} className="text-accent underline-offset-2 hover:underline">Add documents</a>
      </p>
      <div className="mt-5 flex flex-wrap justify-center gap-2">
        {ideas.map((idea) => (
          <button key={idea} type="button" onClick={() => onPick(idea)} className="rounded-full border border-line px-3 py-1.5 text-[13px] text-muted transition hover:border-line-strong hover:bg-raised hover:text-ink">
            {idea}
          </button>
        ))}
      </div>
    </div>
  )
}

function TranscriptSkeleton() {
  return (
    <div className="space-y-7" role="status" aria-label="Loading messages">
      <div className="skeleton ml-auto h-10 w-2/5 rounded-2xl" />
      <div className="space-y-2">
        <div className="skeleton h-4 w-full" />
        <div className="skeleton h-4 w-11/12" />
        <div className="skeleton h-4 w-3/5" />
      </div>
    </div>
  )
}

function Composer({ value, onChange, onSend, onStop, streaming, disabled, autoFocus }) {
  const ref = useRef(null)
  useLayoutEffect(() => {
    const el = ref.current
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 220)}px`
  }, [value])
  useEffect(() => {
    if (autoFocus || value) ref.current?.focus()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [autoFocus, value === ''])
  const submit = () => !disabled && !streaming && value.trim() && onSend(value)
  return (
    <div className="rounded-2xl border border-line-strong bg-surface p-2 shadow-float transition focus-within:border-accent">
      <textarea
        ref={ref}
        rows={1}
        value={value}
        maxLength={32000}
        aria-label="Message"
        placeholder={disabled ? 'Waiting for the AI models…' : 'Message Atlas…'}
        onChange={(e) => onChange(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault()
            submit()
          }
        }}
        className="block max-h-[220px] w-full resize-none bg-transparent px-2.5 py-1.5 text-[15px] outline-none placeholder:text-faint"
      />
      <div className="flex items-center justify-between pl-2.5">
        <span className="hidden text-[11.5px] text-faint sm:block">Enter to send · Shift+Enter for a new line</span>
        <span className="sm:hidden" />
        {streaming ? (
          <button type="button" onClick={onStop} aria-label="Stop generating" className="grid size-8 place-items-center rounded-lg bg-ink text-surface transition hover:opacity-85">
            <Square size={12} fill="currentColor" />
          </button>
        ) : (
          <button type="button" onClick={submit} disabled={disabled || !value.trim()} aria-label="Send message" className="grid size-8 place-items-center rounded-lg bg-accent text-on-accent transition hover:brightness-110 disabled:bg-raised disabled:text-faint">
            <ArrowUp size={17} />
          </button>
        )}
      </div>
    </div>
  )
}

const UserTurn = memo(function UserTurn({ message }) {
  return (
    <div className="animate-rise flex justify-end">
      <div className="max-w-[85%] rounded-2xl rounded-br-md bg-raised px-4 py-2.5 text-[15px] whitespace-pre-wrap break-words">
        {message.content}
      </div>
    </div>
  )
})

// [3] in the answer becomes a clickable citation, except inside code.
const linkCitations = (text) =>
  text.replace(/(```[\s\S]*?(?:```|$)|`[^`\n]*`)|\[(\d{1,3}(?:\s*,\s*\d{1,3})*)\](?!\()/g, (match, code, group) =>
    code ? match : group.split(',').map((n) => `[${n.trim()}](#cite-${n.trim()})`).join(''),
  )

function AssistantTurn({ message, isLast, busy, onSources, onRegenerate, onRate }) {
  const [copied, setCopied] = useState(false)
  const live = message.status === 'streaming'
  const citations = message.citations || []
  const copy = async () => {
    await navigator.clipboard?.writeText(message.content)
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  const components = {
    a({ href, children }) {
      if (href?.startsWith('#cite-')) {
        const n = Number(href.slice(6))
        const known = citations.some((c) => c.n === n)
        if (!known) return <span>[{n}]</span>
        return (
          <button
            type="button"
            aria-label={`Source ${n}`}
            onClick={() => onSources(n)}
            className="mx-0.5 inline-grid h-[18px] min-w-[18px] -translate-y-px place-items-center rounded bg-accent-soft px-1 align-middle font-mono text-[10.5px] font-semibold text-accent transition hover:bg-accent hover:text-on-accent"
          >
            {n}
          </button>
        )
      }
      return <a href={href} target="_blank" rel="noopener noreferrer">{children}</a>
    },
  }
  return (
    <article className="animate-rise group">
      {live && !message.content && (
        <div className="flex items-center gap-2 text-[13.5px] text-muted">
          <Spinner size={14} />
          {citations.length ? 'Thinking…' : 'Checking your documents…'}
        </div>
      )}
      {message.content && (
        <div className={cx('prose-atlas', live && 'caret')}>
          <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
            {linkCitations(message.content)}
          </ReactMarkdown>
        </div>
      )}
      {message.status === 'failed' && (
        <div role="alert" className="mt-2 flex items-center gap-2 rounded-lg bg-bad-soft px-3 py-2 text-[13px] text-bad">
          <AlertTriangle size={14} className="shrink-0" />
          <span className="min-w-0 break-words">{message.error?.message || 'The model failed to answer.'}</span>
        </div>
      )}
      {message.status === 'stopped' && <p className="mt-1.5 text-xs text-faint">Stopped</p>}
      {!live && (
        <div className="-ml-1.5 mt-1.5 flex flex-wrap items-center gap-0.5">
          {citations.length > 0 && (
            <button type="button" onClick={() => onSources(null)} className="mr-1 inline-flex h-7 items-center gap-1.5 rounded-lg border border-line px-2 text-xs text-muted transition hover:bg-raised hover:text-ink">
              <BookOpen size={13} /> {citations.length} source{citations.length > 1 ? 's' : ''}
            </button>
          )}
          {message.content && <IconButton icon={copied ? Check : Copy} size={14} label="Copy answer" className="size-7" onClick={copy} />}
          <IconButton icon={ThumbsUp} size={14} label="Good answer" className="size-7" active={message.feedback?.rating === 'up'} onClick={() => onRate('up')} />
          <IconButton icon={ThumbsDown} size={14} label="Bad answer" className="size-7" active={message.feedback?.rating === 'down'} onClick={() => onRate('down')} />
          {isLast && <IconButton icon={RefreshCw} size={14} label="Regenerate" className="size-7" disabled={busy} onClick={onRegenerate} />}
        </div>
      )}
    </article>
  )
}

function SourcesPanel({ message, focus, pid, onClose }) {
  const refs = useRef({})
  useEffect(() => {
    if (focus) refs.current[focus]?.scrollIntoView({ block: 'nearest', behavior: 'smooth' })
  }, [focus])
  return (
    <aside className="animate-slide fixed inset-y-0 right-0 z-30 flex w-full max-w-[380px] flex-col border-l border-line bg-canvas shadow-float xl:static xl:shadow-none" aria-label="Sources">
      <div className="flex h-12 shrink-0 items-center justify-between border-b border-line pl-4 pr-2">
        <h2 className="font-medium">Sources</h2>
        <IconButton icon={X} label="Close sources" onClick={onClose} />
      </div>
      <ol className="flex-1 space-y-2.5 overflow-y-auto p-3">
        {(message.citations || []).map((c) => (
          <li
            key={c.n}
            ref={(el) => { refs.current[c.n] = el }}
            className={cx('rounded-xl border bg-surface p-3 transition', focus === c.n ? 'border-accent' : 'border-line')}
          >
            <div className="flex items-center gap-2">
              <span className="grid h-[18px] min-w-[18px] place-items-center rounded bg-accent-soft px-1 font-mono text-[10.5px] font-semibold text-accent">{c.n}</span>
              <a href={projectHref(pid, 'documents')} className="flex min-w-0 flex-1 items-center gap-1.5 text-[13px] font-medium hover:text-accent">
                <FileText size={13} className="shrink-0 text-faint" />
                <span className="truncate">{c.document_title}</span>
              </a>
              {c.page > 0 && <span className="shrink-0 text-xs text-faint">p. {c.page}</span>}
            </div>
            <p className="mt-2 line-clamp-[9] whitespace-pre-wrap break-words font-serif text-[14.5px] leading-relaxed text-muted">{c.text}</p>
          </li>
        ))}
      </ol>
    </aside>
  )
}
