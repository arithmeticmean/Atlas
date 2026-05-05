// Small Tailwind-based UI primitives, so the repeated bits (buttons, badges,
// cards, inputs, spinner) are defined once and the pages stay readable. Layout
// utilities live inline in each page; these cover the styled atoms.

export function cx(...parts) {
  return parts.filter(Boolean).join(' ')
}

const BTN_BASE =
  'inline-flex items-center justify-center gap-2 rounded-lg font-medium ' +
  'cursor-pointer transition active:translate-y-px ' +
  'disabled:opacity-45 disabled:cursor-default disabled:active:translate-y-0'

const BTN_VARIANT = {
  default:
    'border border-line-2 bg-elev-2 text-ink hover:border-accent hover:bg-[#212636]',
  primary:
    'border border-transparent text-white ' +
    'bg-[linear-gradient(180deg,var(--color-accent),var(--color-accent-strong))] ' +
    'shadow-[0_6px_18px_-6px_rgb(129_140_248_/_0.4)] hover:brightness-110',
  danger:
    'border border-line-2 bg-elev-2 text-ink ' +
    'hover:border-bad hover:text-bad hover:bg-bad/10',
  ghost:
    'w-full border border-dashed border-line-2 bg-transparent text-dim ' +
    'hover:border-accent hover:text-ink hover:bg-accent/10',
}

const BTN_SIZE = {
  md: 'px-3 py-1.5 text-sm',
  sm: 'px-2.5 py-1 text-xs',
}

export function Button({ variant = 'default', size = 'md', className, ...props }) {
  return (
    <button
      className={cx(BTN_BASE, BTN_VARIANT[variant], BTN_SIZE[size], className)}
      {...props}
    />
  )
}

const BADGE_BASE =
  'inline-block px-2.5 py-0.5 rounded-full text-[11px] font-semibold border'
const BADGE_TONE = {
  dim: 'border-line-2 text-dim bg-elev-2',
  ok: 'text-ok border-ok/35 bg-ok/10',
  warn: 'text-warn border-warn/35 bg-warn/10',
  err: 'text-bad border-bad/40 bg-bad/10',
}

export function Badge({ tone = 'dim', className, ...props }) {
  return (
    <span className={cx(BADGE_BASE, BADGE_TONE[tone], className)} {...props} />
  )
}

export function Card({ className, ...props }) {
  return (
    <div
      className={cx(
        'bg-elev border border-line rounded-xl p-4 mb-3.5 shadow-sm',
        className,
      )}
      {...props}
    />
  )
}

// The "Atlas" wordmark with a gradient on "las".
export function Brand({ className }) {
  return (
    <span className={className}>
      At
      <span className="bg-[linear-gradient(90deg,var(--color-accent),var(--color-accent-2))] bg-clip-text text-transparent">
        las
      </span>
    </span>
  )
}

export function Spinner({ className }) {
  return (
    <span
      className={cx(
        'inline-block w-3.5 h-3.5 rounded-full border-2 border-line-2',
        'border-t-accent animate-spin align-[-2px]',
        className,
      )}
    />
  )
}

// Shared class strings for native form controls (kept native so value/onChange
// stay ergonomic).
export const inputCls =
  'w-full bg-input text-ink border border-line rounded-lg px-3 py-2 outline-none ' +
  'transition placeholder:text-faint focus:border-accent ' +
  'focus:shadow-[0_0_0_3px_rgb(129_140_248_/_0.14)]'

export const labelCls = 'block text-xs text-dim mt-2.5 mb-1'
