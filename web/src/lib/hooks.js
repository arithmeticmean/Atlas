import { useCallback, useEffect, useRef, useState } from 'react'

/** Load once per ``deps``; a stale response never overwrites a newer one. */
export function useLoad(load, deps) {
  const [state, setState] = useState({ data: null, error: null, loading: true })
  const latest = useRef(0)

  const reload = useCallback(async () => {
    const id = ++latest.current
    try {
      const data = await load()
      if (id === latest.current) setState({ data, error: null, loading: false })
      return data
    } catch (error) {
      if (id === latest.current) setState((s) => ({ ...s, error, loading: false }))
      return undefined
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, deps)

  useEffect(() => {
    setState({ data: null, error: null, loading: true })
    reload()
    return () => { latest.current++ }
  }, [reload])

  const setData = useCallback(
    (update) =>
      setState((s) => ({
        ...s,
        data: typeof update === 'function' ? update(s.data) : update,
      })),
    [],
  )
  return { ...state, reload, setData }
}

/** A cursor-paged list with "load more". */
export function usePaged(fetchPage, deps) {
  const list = useLoad(async () => {
    const page = await fetchPage(undefined)
    return { items: page.items, cursor: page.next_cursor }
  }, deps)
  const [loadingMore, setLoadingMore] = useState(false)

  const loadMore = async () => {
    if (!list.data?.cursor || loadingMore) return
    setLoadingMore(true)
    try {
      const page = await fetchPage(list.data.cursor)
      list.setData((d) => ({
        items: [...d.items, ...page.items.filter((x) => !d.items.some((y) => key(y) === key(x)))],
        cursor: page.next_cursor,
      }))
    } finally {
      setLoadingMore(false)
    }
  }
  const setItems = (update) =>
    list.setData((d) => (d ? { ...d, items: update(d.items) } : d))

  return {
    items: list.data?.items ?? null,
    hasMore: Boolean(list.data?.cursor),
    loading: list.loading,
    error: list.error,
    loadingMore,
    loadMore,
    reload: list.reload,
    setItems,
  }
}

const key = (item) => item.id ?? item.user_id

export function useDebounced(value, ms = 250) {
  const [settled, setSettled] = useState(value)
  useEffect(() => {
    const id = setTimeout(() => setSettled(value), ms)
    return () => clearTimeout(id)
  }, [value, ms])
  return settled
}

export function useInterval(callback, ms) {
  const saved = useRef(callback)
  saved.current = callback
  useEffect(() => {
    if (!ms) return undefined
    const id = setInterval(() => {
      if (!document.hidden) saved.current()
    }, ms)
    return () => clearInterval(id)
  }, [ms])
}
