import { useEffect, useState } from 'react'
import { ArrowRight, Check, Moon, Sun, Terminal } from 'lucide-react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { fullDate } from '../lib/format.js'
import { navigate } from '../lib/router.js'
import { useTheme } from '../lib/theme.js'
import { Badge, Button, Contours, IconButton, Notice, PasswordField, Spinner, TextField, Wordmark } from '../ui/index.jsx'

const QUOTES = {
  login: ['Everything your team knows,', 'one question away.'],
  setup: ['Your documents,', 'on your own server.'],
  join: ['Pull up a chair.', 'The map is already drawn.'],
  reset: ['Lost the trail?', "Let's get you back."],
}

function AuthLayout({ kind, title, subtitle, children }) {
  const { theme, toggle } = useTheme()
  const [first, second] = QUOTES[kind]
  return (
    <div className="grid min-h-dvh lg:grid-cols-[minmax(0,1.05fr)_minmax(0,1fr)]">
      <aside className="relative hidden overflow-hidden bg-[#141a18] text-[#ece8dd] lg:flex lg:flex-col lg:justify-between lg:p-11">
        <Contours rings={24} className="absolute -right-[28%] -top-[16%] w-[135%] max-w-none overflow-visible text-[#7f9a8c]" />
        <div className="relative [--accent:#e8804a]"><Wordmark /></div>
        <div className="relative max-w-xl">
          <p className="font-serif text-[44px] leading-[1.08] tracking-tight">
            {first}
            <br />
            <em className="text-[#e8a07a]">{second}</em>
          </p>
          <p className="mt-5 font-mono text-[11px] uppercase tracking-[0.16em] text-[#8c9a92]">
            Self-hosted · Private · Cited answers
          </p>
        </div>
      </aside>
      <main className="relative flex flex-col px-6 py-6 sm:px-10">
        <div className="flex items-center justify-between lg:justify-end">
          <Wordmark className="lg:hidden" />
          <IconButton icon={theme === 'dark' ? Sun : Moon} label="Switch theme" onClick={toggle} />
        </div>
        <div className="flex flex-1 items-center justify-center py-8">
          <div className="animate-rise w-full max-w-[370px]">
            <h1 className="font-serif text-[32px] leading-tight tracking-tight">{title}</h1>
            {subtitle && <p className="mt-1.5 mb-7 text-muted">{subtitle}</p>}
            {children}
          </div>
        </div>
      </main>
    </div>
  )
}

/** Runs ``action`` with a busy flag and an error message. */
function useSubmit(action) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    setError('')
    try {
      await action()
    } catch (e) {
      setError(e.message === 'Failed to fetch' ? "Can't reach the server." : e.message)
    } finally {
      setBusy(false)
    }
  }
  return { busy, error, submit }
}

export function Login() {
  const { startSession } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const { busy, error, submit } = useSubmit(async () => {
    startSession(await api.login({ email: email.trim(), password }))
  })
  return (
    <AuthLayout kind="login" title="Welcome back" subtitle="Sign in to your Atlas workspace.">
      <form onSubmit={submit} className="space-y-4">
        {error && <Notice tone="bad">{error}</Notice>}
        <TextField label="Email" type="email" autoComplete="email" autoFocus required value={email} onChange={(e) => setEmail(e.target.value)} placeholder="you@company.com" />
        <PasswordField label="Password" autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button type="submit" variant="primary" size="lg" busy={busy} className="w-full">
          Sign in {!busy && <ArrowRight size={16} />}
        </Button>
      </form>
      <p className="mt-6 text-center text-[13px] text-muted">
        Forgot your password? Ask an admin for a reset link.
      </p>
    </AuthLayout>
  )
}

export function Setup() {
  const { startSession } = useAuth()
  const [form, setForm] = useState({ token: '', email: '', password: '', confirm: '' })
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  const mismatch = form.confirm && form.password !== form.confirm
  const { busy, error, submit } = useSubmit(async () => {
    if (form.password !== form.confirm) throw new Error("The passwords don't match.")
    const session = await api.setup({ token: form.token.trim(), email: form.email.trim(), password: form.password })
    startSession(session)
    navigate('#/onboarding', { replace: true })
  })
  return (
    <AuthLayout kind="setup" title="Set up Atlas" subtitle="Create the owner account for this server.">
      <form onSubmit={submit} className="space-y-4">
        {error && <Notice tone="bad">{error}</Notice>}
        <div className="flex gap-2.5 rounded-lg bg-raised px-3 py-2.5 text-[13px] text-muted">
          <Terminal size={15} className="mt-0.5 shrink-0" aria-hidden="true" />
          <span>The setup token is printed in the terminal where you started Atlas.</span>
        </div>
        <TextField label="Setup token" required autoFocus autoComplete="off" spellCheck={false} value={form.token} onChange={set('token')} />
        <TextField label="Your email" type="email" autoComplete="email" required value={form.email} onChange={set('email')} placeholder="you@company.com" />
        <PasswordField label="Password" autoComplete="new-password" required minLength={8} hint="At least 8 characters." value={form.password} onChange={set('password')} />
        <PasswordField label="Confirm password" autoComplete="new-password" required value={form.confirm} onChange={set('confirm')} error={mismatch ? "Passwords don't match." : ''} />
        <Button type="submit" variant="primary" size="lg" busy={busy} className="w-full">
          Create owner account
        </Button>
      </form>
    </AuthLayout>
  )
}

export function Join({ token }) {
  const { status, user, startSession, retry } = useAuth()
  const [invite, setInvite] = useState(null)
  const [invalid, setInvalid] = useState('')
  const [form, setForm] = useState({ email: '', username: '', password: '' })
  const set = (key) => (e) => setForm((f) => ({ ...f, [key]: e.target.value }))
  const signedIn = status === 'signed-in'

  useEffect(() => {
    api.resolveInvite(token).then(
      (preview) => {
        setInvite(preview)
        if (preview.email) setForm((f) => ({ ...f, email: preview.email }))
      },
      (e) => setInvalid(e.message),
    )
  }, [token])

  const { busy, error, submit } = useSubmit(async () => {
    if (signedIn) {
      await api.acceptInvite({ token })
      await retry()
    } else {
      const accepted = await api.acceptInvite({ token, ...form, email: form.email.trim() })
      startSession(accepted)
    }
    navigate('#/', { replace: true })
  })

  if (invalid) {
    return (
      <AuthLayout kind="join" title="This invite won't work" subtitle="It may have expired or already been replaced.">
        <Notice tone="bad">{invalid}</Notice>
        <Button className="mt-5 w-full" onClick={() => navigate('#/')}>Back to Atlas</Button>
      </AuthLayout>
    )
  }
  if (!invite) {
    return <div className="grid min-h-dvh place-items-center text-muted"><Spinner size={22} /></div>
  }
  const inviter = invite.invited_by?.username
  return (
    <AuthLayout
      kind="join"
      title="You're invited"
      subtitle={inviter ? `${inviter} invited you to Atlas.` : 'You have been invited to Atlas.'}
    >
      {invite.projects.length > 0 && (
        <ul className="mb-5 divide-y divide-line rounded-lg border border-line bg-surface">
          {invite.projects.map((p) => (
            <li key={p.project_id} className="flex items-center justify-between gap-3 px-3 py-2.5">
              <span className="truncate font-medium">{p.project_name}</span>
              <Badge>{p.role}</Badge>
            </li>
          ))}
        </ul>
      )}
      <form onSubmit={submit} className="space-y-4">
        {error && <Notice tone="bad">{error}</Notice>}
        {signedIn ? (
          <p className="text-muted">Joining as <strong className="text-ink">{user.email}</strong>.</p>
        ) : (
          <>
            <TextField label="Email" type="email" autoComplete="email" required readOnly={Boolean(invite.email)} value={form.email} onChange={set('email')} />
            <TextField label="Username" autoComplete="username" required minLength={3} maxLength={64} value={form.username} onChange={set('username')} />
            <PasswordField label="Password" autoComplete="new-password" required minLength={8} hint="At least 8 characters." value={form.password} onChange={set('password')} />
          </>
        )}
        <Button type="submit" variant="primary" size="lg" busy={busy} icon={Check} className="w-full">
          {signedIn ? 'Accept invite' : 'Create account'}
        </Button>
      </form>
      <p className="mt-5 text-center text-xs text-faint">Invite expires {fullDate(invite.expires_at)}</p>
    </AuthLayout>
  )
}

export function Reset({ token }) {
  const [password, setPassword] = useState('')
  const [done, setDone] = useState(false)
  const { busy, error, submit } = useSubmit(async () => {
    await api.resetPassword({ token, new_password: password })
    setDone(true)
  })
  if (done) {
    return (
      <AuthLayout kind="reset" title="Password updated" subtitle="You can sign in with your new password.">
        <Button variant="primary" size="lg" className="w-full" onClick={() => { window.location.hash = '#/login'; window.location.reload() }}>
          Go to sign in
        </Button>
      </AuthLayout>
    )
  }
  return (
    <AuthLayout kind="reset" title="Choose a new password" subtitle="This link works once.">
      <form onSubmit={submit} className="space-y-4">
        {error && <Notice tone="bad">{error}</Notice>}
        <PasswordField label="New password" autoFocus autoComplete="new-password" required minLength={8} hint="At least 8 characters." value={password} onChange={(e) => setPassword(e.target.value)} />
        <Button type="submit" variant="primary" size="lg" busy={busy} className="w-full">Update password</Button>
      </form>
    </AuthLayout>
  )
}
