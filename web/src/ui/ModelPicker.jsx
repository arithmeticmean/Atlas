import { useEffect, useRef, useState } from 'react'
import { Check, ChevronDown, Plus } from 'lucide-react'
import { cx, inputClass, Spinner } from './index.jsx'

/** Search a provider's models, or type a name it didn't list. */
export default function ModelPicker({ id, value, onChange, models, loading, invalid, placeholder = 'Choose a model' }) {
  const [open, setOpen] = useState(false)
  const [query, setQuery] = useState('')
  const [active, setActive] = useState(0)
  const list = useRef(null)
  const input = useRef(null)

  const typed = query.trim()
  const needle = typed.toLowerCase()
  const matches = needle ? models.filter((m) => m.toLowerCase().includes(needle)) : models
  const custom = typed && !models.includes(typed) ? typed : null
  const options = custom ? [...matches, custom] : matches

  useEffect(() => {
    if (!open) return
    const selected = needle ? 0 : Math.max(0, options.indexOf(value))
    setActive(selected)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, needle, models])

  useEffect(() => {
    if (open) list.current?.querySelector('[data-active="true"]')?.scrollIntoView({ block: 'nearest' })
  }, [active, open])

  const close = () => {
    setOpen(false)
    setQuery('')
  }
  const pick = (model) => {
    onChange(model)
    close()
    input.current?.blur()
  }
  const onKeyDown = (event) => {
    if (event.key === 'Escape' && open) {
      event.preventDefault()
      event.stopPropagation()
      close()
    } else if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      if (!open) return setOpen(true)
      if (options.length) {
        const step = event.key === 'ArrowDown' ? 1 : -1
        setActive((i) => (i + step + options.length) % options.length)
      }
    } else if (event.key === 'Enter' && open) {
      event.preventDefault()
      if (options[active]) pick(options[active])
    }
    return undefined
  }

  const listId = `${id}-models`
  return (
    <div className="relative">
      <input
        ref={input}
        id={id}
        role="combobox"
        aria-expanded={open}
        aria-controls={listId}
        aria-autocomplete="list"
        aria-activedescendant={open && options[active] ? `${listId}-${active}` : undefined}
        aria-invalid={Boolean(invalid)}
        autoComplete="off"
        spellCheck={false}
        className={cx(inputClass, 'pr-9 font-mono text-[13px]')}
        placeholder={open && value ? value : placeholder}
        value={open ? query : value}
        onFocus={() => setOpen(true)}
        onClick={() => setOpen(true)}
        onBlur={close}
        onChange={(e) => {
          setQuery(e.target.value)
          setOpen(true)
        }}
        onKeyDown={onKeyDown}
      />
      <span className="pointer-events-none absolute inset-y-0 right-0 grid w-9 place-items-center text-faint">
        {loading ? <Spinner size={14} /> : <ChevronDown size={15} className={cx('transition-transform', open && 'rotate-180')} />}
      </span>
      {open && (
        <div className="animate-fade absolute inset-x-0 top-full z-30 mt-1.5 overflow-hidden rounded-xl border border-line bg-surface shadow-float">
          <ul ref={list} id={listId} role="listbox" aria-label="Models" className="max-h-64 overflow-y-auto p-1">
            {options.map((model, index) => {
              const isCustom = model === custom
              return (
                <li
                  key={model}
                  id={`${listId}-${index}`}
                  role="option"
                  aria-selected={model === value}
                  data-active={index === active}
                  // mousedown, so the input's blur doesn't close the list first
                  onMouseDown={(e) => {
                    e.preventDefault()
                    pick(model)
                  }}
                  onMouseEnter={() => setActive(index)}
                  className={cx(
                    'flex cursor-pointer items-center gap-2 rounded-lg px-2.5 py-1.5 text-[13px]',
                    index === active && 'bg-raised',
                  )}
                >
                  {isCustom && <Plus size={13} className="shrink-0 text-muted" aria-hidden="true" />}
                  <span className={cx('min-w-0 flex-1 truncate', !isCustom && 'font-mono')}>
                    {isCustom ? `Use “${model}”` : model}
                  </span>
                  {model === value && <Check size={14} className="shrink-0 text-accent" aria-hidden="true" />}
                </li>
              )
            })}
            {options.length === 0 && (
              <li className="px-2.5 py-3 text-center text-[13px] text-muted">
                {loading ? 'Loading models…' : 'No models yet. Type a model name.'}
              </li>
            )}
          </ul>
        </div>
      )}
    </div>
  )
}
