import { useEffect, useMemo, useRef, useState } from 'react'
import { api } from '../lib/api.js'
import { streamAnswer } from '../lib/sse.js'
import SourceRail from './SourceRail.jsx'
import { Brand, cx } from './ui.jsx'

// A message: { role: 'user' | 'assistant', text, sources: [], streaming, error }
//
// Layout: the transcript keeps the centre column and the passages an answer used
// live in a collapsible rail on the right (SourceRail). The [1]/[2] markers the
// model writes into its prose are rendered as buttons that select the matching
// passage, so a citation is something you can follow rather than decoration.
export default function Chat({ projectId, project, railOpen, onOpenDocuments }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  // Which turn's sources the rail is showing, and which of them is highlighted.
  // null turn = follow the newest answer.
  const [focus, setFocus] = useState({ turn: null, n: null })
  const [titles, setTitles] = useState({})
  const abortRef = useRef(null)
  const scrollRef = useRef(null)
  const taRef = useRef(null)

  // The answer stream identifies a passage only by document_id, which is an
  // opaque hex string. The document list already carries the titles, so join
  // them here rather than showing the user an id.
  useEffect(() => {
    let live = true
    setTitles({})
    api
      .listDocuments(projectId)
      .then((docs) => {
        if (!live) return
        setTitles(Object.fromEntries(docs.map((d) => [d.id, d.title])))
      })
      .catch(() => {
        /* titles are a nicety; fall back to the id */
      })
    return () => {
      live = false
    }
  }, [projectId])

  // A new project is a new conversation.
  useEffect(() => {
    setMessages([])
    setFocus({ turn: null, n: null })
  }, [projectId])

  // Keep the transcript pinned to the latest turn as it streams.
  useEffect(() => {
    const el = scrollRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [messages])

  // Auto-grow the composer up to a cap.
  useEffect(() => {
    const el = taRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = Math.min(el.scrollHeight, 200) + 'px'
  }, [input])

  const send = async () => {
    const query = input.trim()
    if (!query || busy) return
    setInput('')
    setBusy(true)

    setMessages((m) => [
      ...m,
      { role: 'user', text: query },
      { role: 'assistant', text: '', sources: [], streaming: true },
    ])
    // Let the rail follow the answer being generated.
    setFocus({ turn: null, n: null })

    const patchLast = (patch) =>
      setMessages((m) => {
        const next = [...m]
        const i = next.length - 1
        next[i] = {
          ...next[i],
          ...(typeof patch === 'function' ? patch(next[i]) : patch),
        }
        return next
      })

    const controller = new AbortController()
    abortRef.current = controller

    await streamAnswer(
      projectId,
      query,
      5,
      {
        onSources: (sources) => patchLast({ sources }),
        onToken: (token) => patchLast((cur) => ({ text: cur.text + token })),
        onDone: () => patchLast({ streaming: false }),
        onError: (message) => patchLast({ streaming: false, error: message }),
      },
      controller.signal,
    )
    setBusy(false)
    abortRef.current = null
  }

  const stop = () => abortRef.current?.abort()

  const onKeyDown = (e) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      send()
    }
  }

  // The rail follows the focused turn, else the most recent answer that has
  // sources -- so it stays useful while you scroll back through a session.
  const railTurn = useMemo(() => {
    if (focus.turn !== null && messages[focus.turn]) return focus.turn
    for (let i = messages.length - 1; i >= 0; i -= 1) {
      if (messages[i].role === 'assistant' && messages[i].sources?.length) return i
    }
    return null
  }, [focus.turn, messages])

  const railSources = useMemo(() => {
    const raw = railTurn === null ? [] : messages[railTurn].sources || []
    return raw.map((s) => ({
      ...s,
      title: titles[s.document_id] || s.document_id || 'unknown document',
    }))
  }, [railTurn, messages, titles])

  const pick = (turn, n) => setFocus({ turn, n })

  const empty = messages.length === 0

  return (
    <div className="flex-1 min-h-0 flex">
      <div className="flex-1 min-w-0 flex flex-col">
        <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
          {empty ? (
            <div className="h-full flex flex-col items-center justify-center text-center px-4">
              <Brand className="text-3xl font-extrabold tracking-tight" />
              <div className="text-dim mt-3 max-w-sm">
                Ask anything about the documents in{' '}
                <span className="text-ink font-medium">{project?.name}</span>.
                Answers stream in with the source passages they used.
              </div>
            </div>
          ) : (
            <div className="max-w-3xl mx-auto w-full px-4 py-6 flex flex-col gap-6">
              {messages.map((msg, i) => (
                <Message
                  key={i}
                  msg={msg}
                  titles={titles}
                  active={i === railTurn}
                  selected={i === railTurn ? focus.n : null}
                  onPick={(n) => pick(i, n)}
                />
              ))}
            </div>
          )}
        </div>

        <div className="shrink-0 bg-[linear-gradient(to_top,var(--color-bg),transparent)]">
          <div className="max-w-3xl mx-auto w-full px-4 pt-2 pb-4">
            <div className="relative rounded-2xl border border-line-2 bg-elev shadow-[0_8px_30px_-12px_rgb(0_0_0_/_0.6)] transition focus-within:border-accent/60 focus-within:shadow-[0_0_0_3px_rgb(129_140_248_/_0.12)]">
              <textarea
                ref={taRef}
                rows={1}
                className="w-full bg-transparent resize-none outline-none text-ink placeholder:text-faint px-4 py-3.5 pr-14 max-h-[200px] leading-6"
                value={input}
                placeholder="Ask a question…"
                onChange={(e) => setInput(e.target.value)}
                onKeyDown={onKeyDown}
              />
              {busy ? (
                <button
                  onClick={stop}
                  title="Stop"
                  className="absolute right-2.5 bottom-2.5 w-9 h-9 rounded-xl flex items-center justify-center bg-elev-2 border border-line-2 text-ink hover:border-bad hover:text-bad transition cursor-pointer"
                >
                  <StopIcon />
                </button>
              ) : (
                <button
                  onClick={send}
                  disabled={!input.trim()}
                  title="Send"
                  className="absolute right-2.5 bottom-2.5 w-9 h-9 rounded-xl flex items-center justify-center text-white transition cursor-pointer disabled:opacity-40 disabled:cursor-default bg-[linear-gradient(180deg,var(--color-accent),var(--color-accent-strong))] enabled:hover:brightness-110 shadow-[0_4px_14px_-4px_rgb(129_140_248_/_0.5)]"
                >
                  <SendIcon />
                </button>
              )}
            </div>
            <div className="text-center text-faint text-[11px] mt-2">
              Enter to send · Shift+Enter for a new line
            </div>
          </div>
        </div>
      </div>

      {railOpen && (
        <SourceRail
          sources={railSources}
          selected={focus.n}
          onSelect={(n) => setFocus({ turn: railTurn, n })}
          onOpenDocument={onOpenDocuments}
        />
      )}
    </div>
  )
}

function Message({ msg, titles, active, selected, onPick }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end animate-[msgin_0.25s_ease]">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-elev-2 border border-line px-4 py-2.5 whitespace-pre-wrap break-words">
          {msg.text}
        </div>
      </div>
    )
  }

  const count = msg.sources?.length || 0

  return (
    <div className="flex gap-3 animate-[msgin_0.25s_ease]">
      <div className="shrink-0 w-7 h-7 rounded-full mt-0.5 grid place-items-center text-[11px] font-bold text-white bg-[linear-gradient(135deg,var(--color-accent),var(--color-accent-2))]">
        A
      </div>
      <div className="flex-1 min-w-0 pt-0.5">
        {msg.error ? (
          <div className="text-bad">Error: {msg.error}</div>
        ) : (
          <div className="whitespace-pre-wrap break-words leading-7">
            <AnswerText
              text={msg.text}
              sources={msg.sources}
              selected={active ? selected : null}
              onPick={onPick}
            />
            {!msg.text && <span className="text-dim">thinking…</span>}
            {msg.streaming && (
              <span className="inline-block w-2 h-4 ml-0.5 align-[-2px] bg-accent rounded-[2px] animate-pulse" />
            )}
          </div>
        )}

        {count > 0 && !msg.error && (
          <div className="mt-3 flex items-center gap-2.5 flex-wrap">
            <span className="text-xs text-dim">
              Grounded in {count} passage{count === 1 ? '' : 's'}
            </span>
            <span className="w-px h-3 bg-line-2" />
            {msg.sources.map((s) => (
              <button
                key={s.n}
                type="button"
                onClick={() => onPick(s.n)}
                className={cx(
                  'text-[11.5px] rounded-full pl-1 pr-2.5 py-0.5 border transition cursor-pointer',
                  'inline-flex items-center gap-1.5 max-w-[220px]',
                  active && selected === s.n
                    ? 'bg-accent/12 border-accent/50 text-ink'
                    : 'bg-elev border-line text-dim hover:border-line-2 hover:text-ink',
                )}
              >
                <span
                  className={cx(
                    'w-4 h-4 rounded grid place-items-center text-[10px] font-bold',
                    active && selected === s.n
                      ? 'bg-accent text-bg'
                      : 'bg-accent/15 text-accent',
                  )}
                >
                  {s.n}
                </span>
                <span className="truncate">
                  {titles[s.document_id] || s.document_id}
                </span>
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}

// Splits streamed answer text on the bracketed citation markers the system
// prompt asks for ("cite the passages you rely on by their bracketed number")
// and renders each as a button. A marker whose number has no matching source
// stays literal text -- the model occasionally cites an index it wasn't given,
// and inventing a chip for it would imply a passage that does not exist.
const CITATION = /\[(\d+)\]/g

function AnswerText({ text, sources, selected, onPick }) {
  const parts = useMemo(() => {
    if (!text) return []
    const known = new Set((sources || []).map((s) => s.n))
    const out = []
    let last = 0
    for (const match of text.matchAll(CITATION)) {
      const n = Number(match[1])
      if (!known.has(n)) continue
      if (match.index > last) out.push(text.slice(last, match.index))
      out.push({ n })
      last = match.index + match[0].length
    }
    if (last < text.length) out.push(text.slice(last))
    return out
  }, [text, sources])

  return parts.map((part, i) =>
    typeof part === 'string' ? (
      part
    ) : (
      <button
        key={`c${i}`}
        type="button"
        onClick={() => onPick(part.n)}
        aria-label={`Show source ${part.n}`}
        className={cx(
          'inline-grid place-items-center min-w-[17px] h-[17px] px-1 mx-px',
          'align-[2px] rounded-[5px] text-[10.5px] font-bold leading-none',
          'border transition cursor-pointer',
          selected === part.n
            ? 'bg-accent border-accent text-bg'
            : 'bg-accent/12 border-accent/25 text-accent hover:bg-accent/20',
        )}
      >
        {part.n}
      </button>
    ),
  )
}

function SendIcon() {
  return (
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor"
      strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round">
      <path d="M12 19V5M5 12l7-7 7 7" />
    </svg>
  )
}

function StopIcon() {
  return (
    <svg viewBox="0 0 24 24" width="16" height="16" fill="currentColor">
      <rect x="6" y="6" width="12" height="12" rx="2.5" />
    </svg>
  )
}
