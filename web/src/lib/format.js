const relative = new Intl.RelativeTimeFormat(undefined, { numeric: 'auto' })
const STEPS = [[60, 'second'], [3600, 'minute'], [86400, 'hour'], [604800, 'day'], [2629800, 'week'], [31557600, 'month']]

export function timeAgo(iso) {
  if (!iso) return 'never'
  const seconds = (new Date(iso) - Date.now()) / 1000
  const size = Math.abs(seconds)
  if (size < 45) return 'just now'
  let unit = 1
  for (const [limit, name] of STEPS) {
    if (size < limit) return relative.format(Math.round(seconds / unit), name)
    unit = limit
  }
  return relative.format(Math.round(seconds / 31557600), 'year')
}

export function fullDate(iso) {
  return iso ? new Date(iso).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' }) : '—'
}

export function fileSize(bytes) {
  if (bytes === null || bytes === undefined) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB', 'TB']
  let value = bytes
  let unit = -1
  do {
    value /= 1024
    unit++
  } while (value >= 1024 && unit < units.length - 1)
  return `${value >= 10 ? value.toFixed(0) : value.toFixed(1)} ${units[unit]}`
}

export function extension(name) {
  const dot = name.lastIndexOf('.')
  return dot > 0 ? name.slice(dot + 1).toLowerCase().slice(0, 5) : 'file'
}

/** Today, Yesterday, Previous 7 days... for the chat list. */
export function dayGroup(iso) {
  if (!iso) return 'Older'
  const start = new Date()
  start.setHours(0, 0, 0, 0)
  const days = (start - new Date(iso)) / 86_400_000
  if (days <= 0) return 'Today'
  if (days <= 1) return 'Yesterday'
  if (days <= 7) return 'Previous 7 days'
  if (days <= 30) return 'Previous 30 days'
  return 'Older'
}
