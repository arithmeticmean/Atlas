import { useAuth } from './lib/auth.jsx'
import { useHashRoute } from './lib/router.js'
import AuthScreen from './components/AuthScreen.jsx'
import Workspace from './components/Workspace.jsx'
import { Brand, Spinner } from './components/ui.jsx'

// Thin top-level router. Rendering is gated purely on the *verified* auth
// status from useAuth() -- never on token presence -- so an unauthenticated
// visitor always lands on the login/invite screen, and only a validated
// session reaches the workspace.
export default function App() {
  const { status } = useAuth()
  const [route, navigate] = useHashRoute()

  if (status === 'checking') return <Splash />

  if (status === 'anon') {
    const invite = route.name === 'invite' ? route.token : ''
    return <AuthScreen initialInvite={invite} />
  }

  return <Workspace route={route} navigate={navigate} />
}

function Splash() {
  return (
    <div className="min-h-screen flex items-center justify-center p-5">
      <div className="text-center">
        <Brand className="text-3xl font-extrabold tracking-tight" />
        <div className="flex items-center justify-center gap-2 mt-3">
          <Spinner />
          <span className="text-dim text-xs">restoring your session…</span>
        </div>
      </div>
    </div>
  )
}
