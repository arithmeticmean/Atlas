import { useEffect } from 'react'
import { WifiOff } from 'lucide-react'
import { useAuth } from './lib/auth.jsx'
import { navigate, useRoute } from './lib/router.js'
import { Button, Empty } from './ui/index.jsx'
import { Join, Login, Reset, Setup } from './pages/Auth.jsx'
import Onboarding from './pages/Onboarding.jsx'
import Shell from './pages/Shell.jsx'

export default function App() {
  const { status, retry, isInstanceAdmin } = useAuth()
  const route = useRoute()

  // The splash in index.html stays until we know which screen to show.
  useEffect(() => {
    if (status === 'loading') {
      document.getElementById('splash')?.classList.remove('done')
    } else {
      document.getElementById('splash')?.classList.add('done')
    }
  }, [status])

  if (status === 'loading') return null
  if (status === 'offline') {
    return (
      <div className="grid min-h-dvh place-items-center">
        <Empty icon={WifiOff} title="Can't reach Atlas" action={<Button variant="primary" onClick={retry}>Try again</Button>}>
          The server isn't responding. Check that it's running, then try again.
        </Empty>
      </div>
    )
  }
  if (route.name === 'join') return <Join token={route.token} />
  if (route.name === 'reset') return <Reset token={route.token} />
  if (status === 'setup') return <Setup />
  if (status === 'signed-out') return <Login />
  if (route.name === 'login' || route.name === 'setup') {
    navigate('#/', { replace: true })
    return null
  }
  if (route.name === 'onboarding' && isInstanceAdmin) return <Onboarding />
  return <Shell route={route} />
}
