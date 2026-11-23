import { useState } from 'react'
import { Check, Copy } from 'lucide-react'
import { fullDate } from '../lib/format.js'
import { Button, inputClass, cx } from '../ui/index.jsx'

/** A secret-ish link, shown once, with a working copy button even over the
 *  plain HTTP many self-hosted servers use (where navigator.clipboard is off). */
export function CopyField({ value }) {
  const [copied, setCopied] = useState(false)
  const copy = async (event) => {
    const input = event.currentTarget.previousSibling
    try {
      await navigator.clipboard.writeText(value)
    } catch {
      input.select()
      document.execCommand('copy')
    }
    setCopied(true)
    setTimeout(() => setCopied(false), 1500)
  }
  return (
    <div className="flex gap-2">
      <input readOnly aria-label="Link" value={value} onFocus={(e) => e.target.select()} className={cx(inputClass, 'font-mono text-xs')} />
      <Button icon={copied ? Check : Copy} className="h-10" onClick={copy}>{copied ? 'Copied' : 'Copy'}</Button>
    </div>
  )
}

export const absoluteUrl = (path) => new URL(path, window.location.origin).href

export function InviteResult({ invite }) {
  return (
    <div className="space-y-2">
      <CopyField value={absoluteUrl(invite.url)} />
      <p className="text-xs text-muted">Expires {fullDate(invite.invite.expires_at)}. Treat it like a password.</p>
    </div>
  )
}
