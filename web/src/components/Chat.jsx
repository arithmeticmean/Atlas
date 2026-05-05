import { useEffect, useRef, useState } from 'react'
import { streamAnswer } from '../lib/sse.js'
import { Brand } from './ui.jsx'

// A message: { role: 'user' | 'assistant', text, sources: [], streaming, error }
export default function Chat({ projectId, project }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const abortRef = useRef(null)
  const scrollRef = useRef(null)
  const taRef = useRef(null)

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

    const patchLast = (patch) =>
      setMessages((m) => {
        const next = [...m]
        const i = next.length - 1
        next[i] = { ...next[i], ...(typeof patch === 'function' ? patch(next[i]) : patch) }
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

  const empty = messages.length === 0

  return (
    <div className="flex-1 min-h-0 flex flex-col">
      {/* transcript */}
      <div ref={scrollRef} className="flex-1 min-h-0 overflow-y-auto">
        {empty ? (
          <div className="h-full flex flex-col items-center justify-center text-center px-4">
            <Brand className="text-3xl font-extrabold tracking-tight" />
            <div className="text-dim mt-3 max-w-sm">
              Ask anything about the documents in{' '}
              <span className="text-ink font-medium">{project?.name}</span>. Answers
              stream in with the source passages they used.
            </div>
          </div>
        ) : (
          <div className="max-w-3xl mx-auto w-full px-4 py-6 flex flex-col gap-6">
            {messages.map((msg, i) => (
              <Message key={i} msg={msg} />
            ))}
          </div>
        )}
      </div>

      {/* composer, pinned to the bottom */}
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
  )
}

function Message({ msg }) {
  if (msg.role === 'user') {
    return (
      <div className="flex justify-end animate-[msgin_0.25s_ease]">
        <div className="max-w-[85%] rounded-2xl rounded-br-md bg-elev-2 border border-line px-4 py-2.5 whitespace-pre-wrap break-words">
          {msg.text}
        </div>
      </div>
    )
  }
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
            {msg.text || <span className="text-dim">thinking…</span>}
            {msg.streaming && (
              <span className="inline-block w-2 h-4 ml-0.5 align-[-2px] bg-accent rounded-[2px] animate-pulse" />
            )}
          </div>
        )}
        {msg.sources && msg.sources.length > 0 && (
          <div className="mt-3 flex flex-col gap-2">
            {msg.sources.map((s) => (
              <div key={s.n} className="bg-input border border-line rounded-lg px-3 py-2.5 text-[13px]">
                <div>
                  <span className="text-accent font-bold mr-1.5">[{s.n}]</span>
                  <span className="font-mono text-xs text-dim">{s.document_id}</span>
                  {typeof s.score === 'number' && (
                    <span className="text-dim text-xs"> · dist {s.score.toFixed(3)}</span>
                  )}
                </div>
                <div className="text-dim mt-1 max-h-[4.5em] overflow-hidden">{s.text}</div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
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
