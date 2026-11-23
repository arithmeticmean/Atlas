import { useCallback, useState } from 'react'

const current = () => document.documentElement.dataset.theme || 'light'

export function useTheme() {
  const [theme, setThemeState] = useState(current)
  const setTheme = useCallback((next) => {
    document.documentElement.dataset.theme = next
    try {
      localStorage.setItem('atlas.theme', next)
    } catch {
      // the choice just won't survive a reload
    }
    setThemeState(next)
  }, [])
  return { theme, setTheme, toggle: () => setTheme(current() === 'dark' ? 'light' : 'dark') }
}
