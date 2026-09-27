import { cx } from './ui.jsx'

// The right-hand rail: the passages one answer was grounded in.
//
// It replaces the stack of cards that used to sit under every assistant turn.
// Those grew without bound -- a ten-turn session was mostly source cards -- and
// they had no connection to the [1]/[2] markers the model writes into the prose.
// Here the markers are buttons and this panel is what they point at.
export default function SourceRail({ sources, selected, onSelect, onOpenDocument }) {
  // `score` is a relevance score: higher is better, whatever retrieval mode
  // produced it. It is not a calibrated probability, so rather than print a
  // percentage the bar shows each passage's standing *relative to the others
  // in this same answer*, and the raw number stays visible.
  const scores = sources.map((s) => s.score).filter((n) => typeof n === 'number')
  const min = Math.min(...scores)
  const max = Math.max(...scores)
  const relative = (score) => {
    if (typeof score !== 'number' || !scores.length) return null
    if (max === min) return 1
    return (score - min) / (max - min)
  }

  return (
    <aside
      className="w-[380px] shrink-0 border-l border-line bg-input flex flex-col"
      aria-label="Sources for this answer"
    >
      <div className="h-[46px] shrink-0 flex items-center gap-2 px-4 border-b border-line">
        <span className="text-[12.5px] font-semibold uppercase tracking-wide text-dim">
          Sources
        </span>
        <span className="text-[11px] text-dim bg-elev-2 border border-line rounded-full px-2 py-px">
          {sources.length}
        </span>
      </div>

      <div className="flex-1 min-h-0 overflow-y-auto p-3.5 flex flex-col gap-2.5">
        {sources.length === 0 ? (
          <p className="text-dim text-[13px] leading-relaxed px-1">
            Passages used to answer will appear here. Ask something to see them.
          </p>
        ) : (
          sources.map((s) => {
            const on = s.n === selected
            const rel = relative(s.score)
            return (
              <button
                key={s.n}
                type="button"
                onClick={() => onSelect(s.n)}
                aria-current={on ? 'true' : undefined}
                className={cx(
                  'text-left rounded-xl p-3 transition cursor-pointer',
                  on
                    ? 'bg-accent/10 border border-accent/40'
                    : 'bg-elev border border-line hover:border-line-2',
                )}
              >
                <div className="flex items-center gap-2.5">
                  <span
                    className={cx(
                      'shrink-0 w-5 h-5 rounded-md grid place-items-center',
                      'text-[11px] font-bold',
                      on ? 'bg-accent text-bg' : 'bg-accent/15 text-accent',
                    )}
                  >
                    {s.n}
                  </span>
                  <span className="flex-1 min-w-0 text-[13px] font-semibold truncate">
                    {s.title}
                  </span>
                </div>

                <div className="flex items-center gap-2 mt-2">
                  {typeof s.chunk_index === 'number' && (
                    <span className="text-[11px] text-dim font-mono">
                      §{s.chunk_index}
                    </span>
                  )}
                  {rel !== null && (
                    <span className="flex-1 h-[3px] rounded-full bg-line overflow-hidden">
                      <span
                        className={cx(
                          'block h-full rounded-full',
                          on ? 'bg-accent' : 'bg-line-2',
                        )}
                        style={{ width: `${Math.round(6 + rel * 94)}%` }}
                      />
                    </span>
                  )}
                  {typeof s.score === 'number' && (
                    <span
                      className="text-[11px] text-dim font-mono"
                      title="Relevance score — higher is better. The bar is relative to the other passages in this answer."
                    >
                      {s.score.toFixed(3)}
                    </span>
                  )}
                </div>

                <p className="text-[12.5px] leading-relaxed text-dim mt-2 whitespace-pre-wrap">
                  {s.text}
                </p>
              </button>
            )
          })
        )}
      </div>

      {sources.length > 0 && onOpenDocument && (
        <div className="shrink-0 border-t border-line p-3">
          <button
            type="button"
            onClick={onOpenDocument}
            className="text-[12px] text-dim hover:text-ink transition cursor-pointer"
          >
            Browse all documents →
          </button>
        </div>
      )}
    </aside>
  )
}
