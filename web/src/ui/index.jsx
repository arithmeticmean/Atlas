// The small design system every page is built from.

import { createContext, useCallback, useContext, useEffect, useId, useMemo, useRef, useState } from 'react'
import { AlertTriangle, Check, Eye, EyeOff, Info, Loader2, X } from 'lucide-react'

export const cx = (...parts) => parts.filter(Boolean).join(' ')

export function Logo({ size = 26, className }) {
  return (
    <svg viewBox="0 0 32 32" width={size} height={size} className={className} aria-hidden="true">
      <circle cx="16" cy="16" r="14.5" fill="none" stroke="currentColor" strokeOpacity=".3" />
      <circle cx="16" cy="16" r="10" fill="none" stroke="currentColor" strokeOpacity=".18" />
      <path d="M16 5.5 23 25 16 20.6 9 25Z" fill="var(--accent)" />
    </svg>
  )
}

export function Wordmark({ className }) {
  return (
    <span className={cx('inline-flex items-center gap-2', className)}>
      <Logo />
      <span className="font-serif text-[21px] leading-none tracking-tight">Atlas</span>
    </span>
  )
}

/** Hand-drawn-looking elevation lines, generated once from a fixed seed. */
export function Contours({ className, rings = 15 }) {
  const paths = useMemo(() => {
    const wobble = (angle, phase) =>
      Math.sin(angle * 2 + phase) * 0.16 + Math.sin(angle * 3 - phase * 1.7) * 0.09 + Math.sin(angle * 5 + phase * 0.6) * 0.04
    return Array.from({ length: rings }, (_, ring) => {
      const radius = 42 + ring * 34
      const phase = 0.7 + ring * 0.13
      const points = Array.from({ length: 72 }, (_, i) => {
        const angle = (i / 72) * Math.PI * 2
        const r = radius * (1 + wobble(angle, phase))
        return `${(420 + Math.cos(angle) * r * 1.15).toFixed(1)} ${(420 + Math.sin(angle) * r).toFixed(1)}`
      })
      return `M${points.join('L')}Z`
    })
  }, [rings])
  return (
    <svg viewBox="0 0 840 840" className={className} aria-hidden="true">
      {paths.map((d, i) => (
        <path
          key={d}
          d={d}
          pathLength="1"
          className="contour"
          strokeWidth={i % 5 === 0 ? 1.1 : 0.6}
          strokeOpacity={i % 5 === 0 ? 0.5 : 0.28}
          style={{ animationDelay: `${i * 55}ms` }}
        />
      ))}
    </svg>
  )
}

export const Spinner = ({ size = 15, className }) => (
  <Loader2 size={size} className={cx('animate-spin', className)} aria-hidden="true" />
)

const BUTTONS = {
  primary: 'bg-accent text-on-accent hover:brightness-[1.07] active:brightness-95 shadow-sm',
  secondary: 'bg-surface text-ink border border-line-strong hover:bg-raised',
  ghost: 'text-muted hover:bg-raised hover:text-ink',
  danger: 'bg-bad text-surface hover:brightness-110',
  'danger-ghost': 'text-bad hover:bg-bad-soft',
}

export function Button({ variant = 'secondary', size = 'md', busy, icon: Icon, className, children, disabled, ...props }) {
  const sizes = { sm: 'h-8 px-2.5 text-[13px] gap-1.5', md: 'h-9 px-3.5 gap-2', lg: 'h-11 px-5 text-[15px] gap-2' }
  return (
    <button
      type="button"
      disabled={disabled || busy}
      className={cx(
        'inline-flex shrink-0 items-center justify-center rounded-lg font-medium whitespace-nowrap transition disabled:opacity-50',
        BUTTONS[variant],
        sizes[size],
        className,
      )}
      {...props}
    >
      {busy ? <Spinner /> : Icon && <Icon size={size === 'sm' ? 14 : 16} aria-hidden="true" />}
      {children}
    </button>
  )
}

export function IconButton({ icon: Icon, label, size = 16, active, className, ...props }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      className={cx(
        'inline-grid size-8 shrink-0 place-items-center rounded-lg transition hover:bg-raised hover:text-ink disabled:opacity-40',
        active ? 'text-accent' : 'text-muted',
        className,
      )}
      {...props}
    >
      <Icon size={size} aria-hidden="true" />
    </button>
  )
}

const inputBase =
  'rounded-lg border border-line-strong bg-surface px-3 text-ink placeholder:text-faint outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/20 disabled:opacity-60'
export const inputClass = `${inputBase} h-10 w-full`
/** For a select sitting inside a row. */
export const compactSelect = `${inputBase} h-8 w-auto text-[13px]`

export function Field({ label, hint, error, children, className }) {
  const id = useId()
  return (
    <div className={className}>
      {label && (
        <label htmlFor={id} className="mb-1.5 block text-[13px] font-medium">
          {label}
        </label>
      )}
      {typeof children === 'function' ? children(id) : children}
      {error ? (
        <p role="alert" className="mt-1.5 text-[12.5px] text-bad">{error}</p>
      ) : (
        hint && <p className="mt-1.5 text-[12.5px] text-muted">{hint}</p>
      )}
    </div>
  )
}

export function TextField({ label, hint, error, className, ...props }) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {(id) => <input id={id} className={inputClass} aria-invalid={Boolean(error)} {...props} />}
    </Field>
  )
}

export function PasswordField({ label, hint, error, className, ...props }) {
  const [shown, setShown] = useState(false)
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {(id) => (
        <div className="relative">
          <input id={id} type={shown ? 'text' : 'password'} className={cx(inputClass, 'pr-10')} {...props} />
          <button
            type="button"
            onClick={() => setShown((v) => !v)}
            aria-label={shown ? 'Hide' : 'Show'}
            className="absolute inset-y-0 right-0 grid w-10 place-items-center text-faint hover:text-ink"
          >
            {shown ? <EyeOff size={16} /> : <Eye size={16} />}
          </button>
        </div>
      )}
    </Field>
  )
}

export function SelectField({ label, hint, error, className, children, ...props }) {
  return (
    <Field label={label} hint={hint} error={error} className={className}>
      {(id) => <select id={id} className={inputClass} {...props}>{children}</select>}
    </Field>
  )
}

const TONES = {
  neutral: 'bg-raised text-muted',
  ok: 'bg-ok-soft text-ok',
  warn: 'bg-warn-soft text-warn',
  bad: 'bg-bad-soft text-bad',
  accent: 'bg-accent-soft text-accent',
}

export function Badge({ tone = 'neutral', children, className }) {
  return (
    <span className={cx('inline-flex h-[22px] items-center gap-1 rounded-md px-2 text-xs font-medium capitalize whitespace-nowrap', TONES[tone], className)}>
      {children}
    </span>
  )
}

export function Notice({ tone = 'neutral', children, action, className }) {
  const Icon = tone === 'bad' || tone === 'warn' ? AlertTriangle : tone === 'ok' ? Check : Info
  return (
    <div role={tone === 'bad' ? 'alert' : 'status'} className={cx('flex items-start gap-2.5 rounded-lg px-3 py-2.5 text-[13px]', TONES[tone], className)}>
      <Icon size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
      <div className="min-w-0 flex-1 break-words">{children}</div>
      {action}
    </div>
  )
}

export const Card = ({ className, children, ...props }) => (
  <section className={cx('rounded-xl border border-line bg-surface', className)} {...props}>{children}</section>
)

export function Empty({ icon: Icon, title, children, action }) {
  return (
    <div className="animate-rise mx-auto flex max-w-sm flex-col items-center px-6 py-16 text-center">
      {Icon && (
        <div className="mb-4 grid size-12 place-items-center rounded-full bg-raised text-muted">
          <Icon size={21} aria-hidden="true" />
        </div>
      )}
      <h3 className="font-serif text-xl">{title}</h3>
      {children && <p className="mt-1.5 text-muted">{children}</p>}
      {action && <div className="mt-5">{action}</div>}
    </div>
  )
}

export function ErrorState({ error, onRetry }) {
  return (
    <Empty icon={AlertTriangle} title="That didn't load" action={onRetry && <Button onClick={onRetry}>Try again</Button>}>
      {error?.message || 'Something went wrong.'}
    </Empty>
  )
}

export const SkeletonRows = ({ rows = 5, className = 'h-12' }) => (
  <div className="space-y-2 p-3" role="status" aria-label="Loading">
    {Array.from({ length: rows }, (_, i) => (
      <div key={i} className={cx('skeleton', className)} style={{ opacity: 1 - i * 0.14 }} />
    ))}
  </div>
)

export function PageHeader({ title, description, children }) {
  return (
    <header className="mb-6 flex flex-wrap items-end justify-between gap-3">
      <div className="min-w-0">
        {title && <h2 className="font-serif text-[26px] leading-tight tracking-tight">{title}</h2>}
        {description && <p className={cx('max-w-xl text-muted', title && 'mt-1')}>{description}</p>}
      </div>
      {children && <div className="flex flex-wrap items-center gap-2">{children}</div>}
    </header>
  )
}

export const Page = ({ children, wide }) => (
  <div className="h-full overflow-y-auto">
    <div className={cx('animate-rise mx-auto w-full px-4 py-7 sm:px-8', wide ? 'max-w-6xl' : 'max-w-3xl')}>{children}</div>
  </div>
)

export function Modal({ open, onClose, title, description, children, footer, wide }) {
  const ref = useRef(null)
  useEffect(() => {
    const dialog = ref.current
    if (open && !dialog.open) dialog.showModal()
    if (!open && dialog.open) dialog.close()
  }, [open])
  return (
    <dialog
      ref={ref}
      onClose={onClose}
      onClick={(e) => e.target === ref.current && onClose()}
      className={cx('m-auto w-[calc(100%-2rem)] rounded-2xl border border-line bg-surface p-0 shadow-float open:animate-rise', wide ? 'max-w-xl' : 'max-w-md')}
    >
      {open && (
        <div className="flex max-h-[85dvh] flex-col">
          <div className="flex items-start justify-between gap-3 px-5 pt-5">
            <div>
              <h2 className="font-serif text-xl leading-tight">{title}</h2>
              {description && <p className="mt-1 text-[13px] text-muted">{description}</p>}
            </div>
            <IconButton icon={X} label="Close" onClick={onClose} className="-mr-1.5 -mt-1" />
          </div>
          <div className="overflow-y-auto px-5 py-4">{children}</div>
          {footer && <div className="flex justify-end gap-2 border-t border-line px-5 py-3.5">{footer}</div>}
        </div>
      )}
    </dialog>
  )
}

/** A dropdown. ``children`` is a function given ``close``. */
export function Menu({ trigger, children, align = 'right', side = 'down', className }) {
  const [open, setOpen] = useState(false)
  const root = useRef(null)
  useEffect(() => {
    if (!open) return undefined
    const onDown = (e) => !root.current?.contains(e.target) && setOpen(false)
    const onKey = (e) => e.key === 'Escape' && setOpen(false)
    document.addEventListener('mousedown', onDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('mousedown', onDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])
  return (
    <div ref={root} className={cx('relative', className)}>
      {trigger({ open, toggle: () => setOpen((v) => !v) })}
      {open && (
        <div
          role="menu"
          className={cx(
            'animate-fade absolute z-40 min-w-48 rounded-xl border border-line bg-surface p-1 shadow-float',
            align === 'right' ? 'right-0' : 'left-0',
            side === 'up' ? 'bottom-full mb-1.5' : 'top-full mt-1.5',
          )}
        >
          {children(() => setOpen(false))}
        </div>
      )}
    </div>
  )
}

export function MenuItem({ icon: Icon, danger, children, ...props }) {
  return (
    <button
      type="button"
      role="menuitem"
      className={cx(
        'flex w-full items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-left text-[13.5px] transition',
        danger ? 'text-bad hover:bg-bad-soft' : 'hover:bg-raised',
      )}
      {...props}
    >
      {Icon && <Icon size={15} className={danger ? '' : 'text-muted'} aria-hidden="true" />}
      <span className="min-w-0 flex-1 truncate">{children}</span>
    </button>
  )
}

// --- toasts and confirmation, available anywhere ----------------------------

const FeedbackContext = createContext(null)
export const useToast = () => useContext(FeedbackContext).toast
export const useConfirm = () => useContext(FeedbackContext).confirm

export function FeedbackProvider({ children }) {
  const [toasts, setToasts] = useState([])
  const [asking, setAsking] = useState(null)
  const nextId = useRef(0)

  const dismiss = useCallback((id) => setToasts((all) => all.filter((t) => t.id !== id)), [])
  const toast = useMemo(() => {
    const show = (tone, message) => {
      const id = ++nextId.current
      setToasts((all) => [...all.slice(-3), { id, tone, message }])
      setTimeout(() => dismiss(id), tone === 'bad' ? 7000 : 3500)
    }
    return {
      ok: (message) => show('ok', message),
      info: (message) => show('neutral', message),
      error: (error) => show('bad', error?.message || String(error)),
    }
  }, [dismiss])

  const confirm = useCallback(
    (options) => new Promise((resolve) => setAsking({ ...options, resolve })),
    [],
  )
  const answer = (value) => {
    asking?.resolve(value)
    setAsking(null)
  }
  const value = useMemo(() => ({ toast, confirm }), [toast, confirm])

  return (
    <FeedbackContext.Provider value={value}>
      {children}
      <div aria-live="polite" className="pointer-events-none fixed inset-x-4 bottom-4 z-[60] flex flex-col items-center gap-2 sm:left-auto sm:w-96 sm:items-end">
        {toasts.map((t) => (
          <div key={t.id} className="animate-slide pointer-events-auto flex w-full items-start gap-2.5 rounded-xl border border-line bg-surface p-3 text-[13.5px] shadow-float">
            <span className={cx('mt-0.5', t.tone === 'bad' ? 'text-bad' : t.tone === 'ok' ? 'text-ok' : 'text-muted')}>
              {t.tone === 'bad' ? <AlertTriangle size={15} /> : t.tone === 'ok' ? <Check size={15} /> : <Info size={15} />}
            </span>
            <span className="min-w-0 flex-1 break-words">{t.message}</span>
            <button type="button" aria-label="Dismiss" onClick={() => dismiss(t.id)} className="text-faint hover:text-ink">
              <X size={14} />
            </button>
          </div>
        ))}
      </div>
      <Modal
        open={Boolean(asking)}
        onClose={() => answer(false)}
        title={asking?.title}
        footer={
          <>
            <Button onClick={() => answer(false)}>Cancel</Button>
            <Button variant={asking?.danger ? 'danger' : 'primary'} onClick={() => answer(true)}>
              {asking?.action || 'Confirm'}
            </Button>
          </>
        }
      >
        <p className="text-muted">{asking?.message}</p>
      </Modal>
    </FeedbackContext.Provider>
  )
}
