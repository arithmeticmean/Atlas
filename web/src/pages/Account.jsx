import { useState } from 'react'
import { Moon, Sun } from 'lucide-react'
import { api } from '../lib/api.js'
import { useAuth } from '../lib/auth.jsx'
import { useTheme } from '../lib/theme.js'
import { Badge, Button, Card, cx, Page, PageHeader, PasswordField, TextField, useToast } from '../ui/index.jsx'

export default function Account() {
  const { user, setUser } = useAuth()
  const { theme, setTheme } = useTheme()
  const toast = useToast()
  const [username, setUsername] = useState(user.username)
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [busy, setBusy] = useState('')

  const saveName = async (event) => {
    event.preventDefault()
    setBusy('name')
    try {
      setUser(await api.updateMe({ username: username.trim() }))
      toast.ok('Username updated')
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy('')
    }
  }
  const savePassword = async (event) => {
    event.preventDefault()
    setBusy('password')
    try {
      await api.changePassword({ current_password: current, new_password: next })
      setCurrent('')
      setNext('')
      toast.ok('Password changed')
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy('')
    }
  }
  return (
    <Page>
      <PageHeader title="Account" />
      <div className="space-y-5">
        <Card className="p-5">
          <div className="mb-4 flex items-center gap-3">
            <span className="grid size-12 place-items-center rounded-full bg-accent-soft font-serif text-xl uppercase text-accent">{user.username[0]}</span>
            <div className="min-w-0">
              <p className="truncate font-medium">{user.email}</p>
              <Badge>{user.role}</Badge>
            </div>
          </div>
          <form onSubmit={saveName} className="flex items-end gap-2">
            <TextField label="Username" className="flex-1" required minLength={3} maxLength={64} value={username} onChange={(e) => setUsername(e.target.value)} />
            <Button type="submit" variant="primary" className="h-10" busy={busy === 'name'} disabled={username.trim() === user.username}>Save</Button>
          </form>
        </Card>
        <Card className="p-5">
          <h2 className="mb-3 font-serif text-xl">Appearance</h2>
          <div className="grid grid-cols-2 gap-2">
            {[['light', 'Paper', Sun], ['dark', 'Night', Moon]].map(([key, label, Icon]) => (
              <button
                key={key}
                type="button"
                aria-pressed={theme === key}
                onClick={() => setTheme(key)}
                className={cx('flex items-center gap-2 rounded-lg border p-3 font-medium transition', theme === key ? 'border-accent bg-accent-soft/60' : 'border-line hover:border-line-strong')}
              >
                <Icon size={16} /> {label}
              </button>
            ))}
          </div>
        </Card>
        <Card className="p-5">
          <h2 className="mb-3 font-serif text-xl">Password</h2>
          <form onSubmit={savePassword} className="space-y-3">
            <PasswordField label="Current password" autoComplete="current-password" required value={current} onChange={(e) => setCurrent(e.target.value)} />
            <PasswordField label="New password" autoComplete="new-password" required minLength={8} hint="At least 8 characters." value={next} onChange={(e) => setNext(e.target.value)} />
            <Button type="submit" variant="primary" busy={busy === 'password'}>Change password</Button>
          </form>
        </Card>
      </div>
    </Page>
  )
}
