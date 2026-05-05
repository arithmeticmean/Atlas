import { useState } from 'react'
import { useAuth } from '../lib/auth.jsx'
import { go } from '../lib/router.js'
import { Brand, Button, Spinner, cx, inputCls, labelCls } from './ui.jsx'

// The unauthenticated gate: sign in, or redeem an invite to create an account
// (and, for a project invite, join that project). It talks to the auth context
// only; on success the context flips to 'authed' and <App> swaps to the
// workspace. We also clear the hash so the URL leaves /login|/invite.
export default function AuthScreen({ initialInvite = '' }) {
  const [mode, setMode] = useState(initialInvite ? 'invite' : 'signin')

  const tab = (id, label) => (
    <button
      onClick={() => setMode(id)}
      className={cx(
        'flex-1 rounded-md px-2.5 py-1.5 text-sm border transition cursor-pointer',
        mode === id
          ? 'bg-accent/15 text-[#c7cdfb] border-accent/30 font-semibold'
          : 'bg-transparent text-dim border-transparent hover:bg-elev-2',
      )}
    >
      {label}
    </button>
  )

  return (
    <div className="min-h-screen flex items-center justify-center p-5">
      <div className="w-full max-w-[370px] bg-elev border border-line rounded-2xl p-7 shadow-[0_1px_2px_rgb(0_0_0_/_0.35),0_10px_30px_-12px_rgb(0_0_0_/_0.55)]">
        <Brand className="block text-3xl font-extrabold text-center" />
        <div className="text-dim text-xs text-center mt-1">self-hosted RAG</div>

        <div className="flex gap-1 mt-4 p-1 bg-input border border-line rounded-[10px]">
          {tab('signin', 'Sign in')}
          {tab('invite', 'Have an invite?')}
        </div>

        {mode === 'signin' ? (
          <SignIn />
        ) : (
          <AcceptInvite initialInvite={initialInvite} />
        )}
      </div>
    </div>
  )
}

function SignIn() {
  const { signIn } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true); setError('')
    try {
      await signIn(email.trim(), password)
      go('#/')
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  return (
    <div>
      <label className={labelCls}>Email</label>
      <input className={inputCls} value={email} type="email" autoComplete="username"
        onChange={(e) => setEmail(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()} />
      <label className={labelCls}>Password</label>
      <input className={inputCls} value={password} type="password" autoComplete="current-password"
        onChange={(e) => setPassword(e.target.value)}
        onKeyDown={(e) => e.key === 'Enter' && submit()} />
      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      <Button variant="primary" className="w-full mt-4" onClick={submit}
        disabled={busy || !email || !password}>
        {busy ? <Spinner /> : 'Sign in'}
      </Button>
    </div>
  )
}

function AcceptInvite({ initialInvite }) {
  const { redeemInvite } = useAuth()
  const [invite, setInvite] = useState(initialInvite)
  const [email, setEmail] = useState('')
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  const submit = async () => {
    setBusy(true); setError('')
    try {
      await redeemInvite(invite.trim(), {
        email: email.trim(),
        username: username.trim(),
        password,
      })
      go('#/')
    } catch (e) {
      setError(e.message)
    }
    setBusy(false)
  }

  return (
    <div>
      <label className={labelCls}>Invite token</label>
      <input className={inputCls} value={invite}
        onChange={(e) => setInvite(e.target.value)}
        placeholder="paste the invite token" />
      <label className={labelCls}>Email</label>
      <input className={inputCls} value={email} type="email"
        onChange={(e) => setEmail(e.target.value)} />
      <label className={labelCls}>Username</label>
      <input className={inputCls} value={username}
        onChange={(e) => setUsername(e.target.value)}
        placeholder="3–64 characters" />
      <label className={labelCls}>Password</label>
      <input className={inputCls} value={password} type="password"
        onChange={(e) => setPassword(e.target.value)} />
      <div className="text-dim text-xs mt-1">at least 8 characters</div>
      {error && <div className="text-bad text-[13px] mt-3">{error}</div>}
      <Button variant="primary" className="w-full mt-4" onClick={submit}
        disabled={busy || !invite || !email || !username || !password}>
        {busy ? <Spinner /> : 'Create account'}
      </Button>
    </div>
  )
}
