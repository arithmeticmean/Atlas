import { useCallback, useEffect, useRef, useState } from 'react'
import { AlertTriangle, ArrowUpRight, Check, CheckCircle2, Zap } from 'lucide-react'
import { api } from '../lib/api.js'
import { useInterval, useLoad } from '../lib/hooks.js'
import {
  Badge, Button, Card, cx, ErrorState, Field, inputClass, Notice, Page, PageHeader, PasswordField, SkeletonRows, Spinner, TextField, useConfirm, useToast,
} from '../ui/index.jsx'
import ModelPicker from '../ui/ModelPicker.jsx'
import { SystemStatus, UsersAdmin } from './Admin.jsx'

const TABS = [
  ['ai', 'AI models'],
  ['knowledge', 'Answers & documents'],
  ['users', 'Users'],
  ['system', 'System'],
]

export default function SettingsLayout({ page }) {
  return (
    <div className="flex h-full flex-col">
      <div className="shrink-0 border-b border-line">
        <div className="mx-auto max-w-3xl px-4 pt-5 sm:px-8">
        <h1 className="font-serif text-[28px] leading-tight tracking-tight">Settings</h1>
        <nav aria-label="Settings" className="mt-3 flex gap-5 overflow-x-auto">
          {TABS.map(([key, label]) => (
            <a
              key={key}
              href={`#/admin/${key}`}
              aria-current={page === key ? 'page' : undefined}
              className={cx(
                'border-b-2 pb-2.5 text-[13.5px] whitespace-nowrap transition',
                page === key ? 'border-accent font-medium text-ink' : 'border-transparent text-muted hover:text-ink',
              )}
            >
              {label}
            </a>
          ))}
        </nav>
        </div>
      </div>
      <div className="min-h-0 flex-1">
        {page === 'users' ? <UsersAdmin /> : page === 'system' ? <SystemStatus /> : page === 'knowledge' ? <Knowledge /> : <AIModels />}
      </div>
    </div>
  )
}

// --- AI models ----------------------------------------------------------------

export const SLOTS = {
  chat: {
    title: 'Chat model',
    blurb: 'Reads the passages Atlas finds and writes the answer.',
    provider: 'llm_provider',
    model: 'llm_model',
    url: 'llm_base_url',
    key: 'llm_api_key',
    status: 'llm',
  },
  embedding: {
    title: 'Embedding model',
    blurb: 'Turns your documents into something searchable by meaning.',
    provider: 'embedding_provider',
    model: 'embedding_model',
    url: 'embedding_base_url',
    key: 'embedding_api_key',
    status: 'embedding',
  },
}

const PROVIDER_COPY = {
  ollama: { blurb: 'Runs on your own machine. Free and private.' },
  openai: { blurb: 'GPT models, hosted by OpenAI.', keys: 'https://platform.openai.com/api-keys' },
  anthropic: { blurb: 'Claude models, hosted by Anthropic.', keys: 'https://console.anthropic.com/settings/keys' },
  google: { blurb: 'Gemini models, hosted by Google.', keys: 'https://aistudio.google.com/apikey' },
  openai_compatible: { blurb: 'LM Studio, vLLM, OpenRouter and similar.' },
}

const isUrl = (value) => /^https?:\/\/\S+$/i.test(value.trim())

const providerName = (providers, key) =>
  key === 'fake' ? 'Test embeddings' : providers.find((p) => p.key === key)?.name || key

function AIModels() {
  const settings = useLoad(() => api.settings(), [])
  const providers = useLoad(() => api.providers(), [])
  const status = useLoad(() => api.status(), [])
  const [editing, setEditing] = useState(null)
  useInterval(status.reload, editing ? null : 6000)

  if (settings.error) return <Page><ErrorState error={settings.error} onRetry={settings.reload} /></Page>
  if (!settings.data || !providers.data) {
    return <Page><Card><SkeletonRows rows={2} className="h-20" /></Card></Page>
  }
  return (
    <Page>
      <PageHeader description="Atlas uses two models. API keys are encrypted and never shown again." />
      <div className="space-y-3">
        {Object.entries(SLOTS).map(([kind, slot]) => {
          const health = status.data?.[slot.status]
          const isOpen = editing === kind
          return (
            <Card key={kind} className={cx('transition', isOpen && 'border-line-strong shadow-float')}>
              <div className="flex items-center gap-3.5 p-4">
                <ProviderMark name={providerName(providers.data, settings.data.values[slot.provider])} />
                <div className="min-w-0 flex-1">
                  <h2 className="font-medium">{slot.title}</h2>
                  <p className="truncate text-[13px] text-muted">
                    {providerName(providers.data, settings.data.values[slot.provider])}
                    <span className="text-faint"> · </span>
                    <span className="font-mono text-xs">{settings.data.values[slot.model]}</span>
                  </p>
                  {health && !health.ok && !isOpen && <p className="mt-0.5 text-[12.5px] text-bad">{health.detail}</p>}
                </div>
                {health && (
                  <Badge tone={health.ok ? 'ok' : 'bad'} className="max-sm:hidden">
                    {health.ok ? 'Connected' : 'Not connected'}
                  </Badge>
                )}
                {!isOpen && <Button size="sm" onClick={() => setEditing(kind)}>Change</Button>}
              </div>
              {isOpen && (
                <div className="animate-fade border-t border-line p-4 sm:p-5">
                  <ModelEditor
                    kind={kind}
                    settings={settings.data}
                    providers={providers.data}
                    onCancel={() => setEditing(null)}
                    onSaved={async () => {
                      setEditing(null)
                      await Promise.all([settings.reload(), status.reload()])
                    }}
                  />
                </div>
              )}
            </Card>
          )
        })}
      </div>
    </Page>
  )
}

const ProviderMark = ({ name, small }) => (
  <span className={cx('grid shrink-0 place-items-center rounded-lg bg-accent-soft font-serif text-accent', small ? 'size-8 text-[15px]' : 'size-10 text-lg')} aria-hidden="true">
    {name[0]}
  </span>
)

/** Choose a provider, connect, pick a model. The model list loads as soon as
 *  the connection details are there, so a bad key shows up right away. */
export function ModelEditor({ kind, settings, providers, initialProvider, onSaved, onCancel, onSkip, saveLabel = 'Save', autoConfirm = false }) {
  const slot = SLOTS[kind]
  const toast = useToast()
  const confirm = useConfirm()
  const { values, secrets_set: secretsSet } = settings
  const savedProvider = values[slot.provider]
  const savedUrl = values[slot.url] || ''

  const [provider, setProvider] = useState(initialProvider || savedProvider)
  const [model, setModel] = useState(provider === savedProvider ? values[slot.model] : '')
  const [url, setUrl] = useState(provider === savedProvider ? savedUrl : '')
  const [ollamaUrl, setOllamaUrl] = useState(values.ollama_base_url)
  const [key, setKey] = useState('')
  const [models, setModels] = useState({ state: 'idle', list: [], error: '' })
  const [errors, setErrors] = useState({})
  const [check, setCheck] = useState(null)
  const [busy, setBusy] = useState('')
  const request = useRef(0)

  const info = providers.find((p) => p.key === provider)
  const options = providers.filter((p) => kind === 'chat' || p.supports_embeddings)
  const cleanUrl = url.trim()
  const sameEndpoint = provider === savedProvider && cleanUrl === savedUrl
  const ownKeySaved = secretsSet.includes(slot.key)
  const sharedKey = `${provider}_api_key`
  const keySaved = (ownKeySaved && sameEndpoint) || (Boolean(info?.needs_api_key) && !cleanUrl && secretsSet.includes(sharedKey))
  const showUrl = Boolean(info?.needs_base_url) || Boolean(cleanUrl && provider !== 'ollama')
  const showKey = Boolean(info?.needs_api_key || info?.needs_base_url)
  const connectable = Boolean(info) && (!info.needs_api_key || Boolean(key.trim()) || keySaved) && (!info.needs_base_url || isUrl(cleanUrl)) && (provider !== 'ollama' || isUrl(ollamaUrl))
  const rebuilds = kind === 'embedding' && (provider !== savedProvider || model !== values[slot.model])
  const changed = provider !== savedProvider || model !== values[slot.model] || cleanUrl !== savedUrl || Boolean(key.trim()) || (provider === 'ollama' && ollamaUrl !== values.ollama_base_url)

  const loadModels = useCallback(async () => {
    const id = ++request.current
    if (!connectable) {
      setModels({ state: 'idle', list: [], error: '' })
      return
    }
    setModels((m) => ({ ...m, state: 'loading', error: '' }))
    try {
      const { models: list } = await api.models({
        provider,
        kind,
        api_key: key.trim() || null,
        base_url: provider === 'ollama' ? ollamaUrl.trim() : cleanUrl || null,
      })
      if (id !== request.current) return
      setModels({ state: 'ready', list, error: '' })
      if (list.length === 1) setModel((m) => m || list[0])
    } catch (e) {
      if (id === request.current) setModels({ state: 'error', list: [], error: e.message })
    }
  }, [connectable, provider, kind, key, ollamaUrl, cleanUrl])

  // On opening and on switching provider. Keys and URLs load on blur instead,
  // so a half-typed key is never sent anywhere.
  useEffect(() => {
    loadModels()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [provider])

  const choose = (next) => {
    if (next === provider) return
    request.current++
    setProvider(next)
    setModel(next === savedProvider ? values[slot.model] : '')
    setUrl(next === savedProvider ? savedUrl : '')
    setKey('')
    setErrors({})
    setCheck(null)
    setModels({ state: 'idle', list: [], error: '' })
  }

  const payload = () => {
    const nextValues = {
      [slot.provider]: provider,
      [slot.model]: model.trim(),
      [slot.url]: cleanUrl || null,
    }
    if (provider === 'ollama') nextValues.ollama_base_url = ollamaUrl.trim()
    const nextSecrets = {}
    const typed = key.trim()
    if (typed && info.needs_api_key && !cleanUrl) {
      // Shared, so chat and embeddings on one provider need one key.
      nextSecrets[sharedKey] = typed
      if (ownKeySaved) nextSecrets[slot.key] = null
    } else if (typed) {
      nextSecrets[slot.key] = typed
    } else if (ownKeySaved && !sameEndpoint) {
      nextSecrets[slot.key] = null
    }
    return { values: nextValues, secrets: nextSecrets }
  }

  const validate = () => {
    const found = {}
    if (info?.needs_base_url && !cleanUrl) found.url = 'Enter the server address.'
    if (cleanUrl && !isUrl(cleanUrl)) found.url = 'Enter a full address, like http://localhost:1234/v1.'
    if (provider === 'ollama' && !isUrl(ollamaUrl)) found.ollama = 'Enter a full address, like http://localhost:11434.'
    if (info?.needs_api_key && !key.trim() && !keySaved) found.key = 'Enter your API key.'
    if (!model.trim()) found.model = 'Choose a model.'
    setErrors(found)
    return Object.keys(found).length === 0
  }

  const showFailure = (e) => {
    const fields = Object.fromEntries((e.fields || []).map((f) => [f.field, f.message]))
    const mapped = {
      url: fields[slot.url],
      key: fields[slot.key] || fields[sharedKey],
      model: fields[slot.model],
      ollama: fields.ollama_base_url,
    }
    const connection = fields[kind]
    if (connection) setCheck({ ok: false, detail: connection })
    if (connection || Object.values(mapped).some(Boolean)) setErrors(mapped)
    else toast.error(e)
  }

  const test = async () => {
    if (!validate()) return
    setBusy('test')
    setCheck(null)
    try {
      const result = await api.testSettings({ ...payload(), kind })
      setCheck(kind === 'chat' ? result.chat : result.embeddings)
    } catch (e) {
      showFailure(e)
    } finally {
      setBusy('')
    }
  }

  const save = async () => {
    if (!validate()) return
    if (rebuilds && !autoConfirm) {
      const yes = await confirm({
        title: 'Rebuild the search index?',
        message: 'A new embedding model means every document is indexed again. Uploads and answers pause until it finishes.',
        action: 'Save and rebuild',
      })
      if (!yes) return
    }
    setBusy('save')
    setCheck(null)
    try {
      await api.saveSettings({ ...payload(), confirm_reindex: rebuilds })
      toast.ok(`${slot.title} saved`)
      await onSaved()
    } catch (e) {
      showFailure(e)
    } finally {
      setBusy('')
    }
  }

  const keysLink = PROVIDER_COPY[provider]?.keys
  return (
    <div className="space-y-5">
      <fieldset>
        <legend className="mb-2 text-[13px] font-medium">Provider</legend>
        <div className="grid gap-2 sm:grid-cols-2">
          {options.map((p) => {
            const active = p.key === provider
            return (
              <button
                key={p.key}
                type="button"
                aria-pressed={active}
                onClick={() => choose(p.key)}
                className={cx(
                  'flex items-center gap-3 rounded-xl border p-3 text-left transition',
                  active ? 'border-accent bg-accent-soft/40 ring-1 ring-accent' : 'border-line hover:border-line-strong hover:bg-raised/50',
                )}
              >
                <ProviderMark name={p.name} small />
                <span className="min-w-0 flex-1">
                  <span className="block font-medium leading-tight">{p.name}</span>
                  <span className="block text-xs leading-snug text-muted">{PROVIDER_COPY[p.key]?.blurb}</span>
                </span>
                {active && <Check size={15} className="shrink-0 text-accent" aria-hidden="true" />}
              </button>
            )
          })}
        </div>
      </fieldset>

      {info && (
        <div className="space-y-4">
          {provider === 'ollama' && (
            <TextField
              label="Ollama address"
              spellCheck={false}
              value={ollamaUrl}
              error={errors.ollama}
              onChange={(e) => { setOllamaUrl(e.target.value); setErrors({}); setCheck(null) }}
              onBlur={loadModels}
            />
          )}
          {showUrl && (
            <TextField
              label="Server address"
              spellCheck={false}
              placeholder="http://localhost:1234/v1"
              value={url}
              error={errors.url}
              onChange={(e) => { setUrl(e.target.value); setErrors({}); setCheck(null) }}
              onBlur={loadModels}
            />
          )}
          {showKey && (
            <div>
              <PasswordField
                label={info.needs_api_key ? 'API key' : 'API key (if your server needs one)'}
                autoComplete="off"
                spellCheck={false}
                placeholder={keySaved ? 'Saved. Type to replace it.' : ''}
                value={key}
                error={errors.key}
                onChange={(e) => { setKey(e.target.value); setErrors({}); setCheck(null) }}
                onBlur={loadModels}
              />
              {keysLink && !keySaved && (
                <a href={keysLink} target="_blank" rel="noopener noreferrer" className="mt-1.5 inline-flex items-center gap-0.5 text-[12.5px] text-accent hover:underline">
                  Get an API key <ArrowUpRight size={13} aria-hidden="true" />
                </a>
              )}
            </div>
          )}
          <Field label="Model" error={errors.model}>
            {(id) => (
              <ModelPicker
                id={id}
                value={model}
                models={models.list}
                loading={models.state === 'loading'}
                invalid={errors.model}
                onChange={(next) => { setModel(next); setErrors({}); setCheck(null) }}
              />
            )}
          </Field>
          <div className="min-h-5"><ConnectionLine models={models} connectable={connectable} provider={info} /></div>
        </div>
      )}

      {rebuilds && !autoConfirm && model && (
        <Notice tone="warn">Saving this rebuilds the search index for every document.</Notice>
      )}
      {check && (
        <Notice tone={check.ok ? 'ok' : 'bad'}>{check.ok ? 'It works. The model answered.' : check.detail}</Notice>
      )}

      <div className="flex flex-wrap items-center gap-2 border-t border-line pt-4">
        <Button icon={Zap} busy={busy === 'test'} disabled={Boolean(busy)} onClick={test}>Test</Button>
        <div className="flex-1" />
        {onSkip && <Button variant="ghost" disabled={Boolean(busy)} onClick={onSkip}>Skip for now</Button>}
        {onCancel && <Button variant="ghost" disabled={Boolean(busy)} onClick={onCancel}>Cancel</Button>}
        <Button variant="primary" busy={busy === 'save'} disabled={Boolean(busy) || (!changed && !onSkip)} onClick={save}>
          {busy === 'save' ? 'Checking…' : saveLabel}
        </Button>
      </div>
    </div>
  )
}

function ConnectionLine({ models, connectable, provider }) {
  if (!connectable) {
    return <p className="text-[12.5px] text-muted">Add the details above to see {provider.name}'s models.</p>
  }
  if (models.state === 'loading') {
    return <p className="flex items-center gap-1.5 text-[12.5px] text-muted"><Spinner size={12} /> Connecting to {provider.name}…</p>
  }
  if (models.state === 'error') {
    return <p role="alert" className="flex items-start gap-1.5 text-[12.5px] text-bad"><AlertTriangle size={13} className="mt-0.5 shrink-0" /> {models.error}</p>
  }
  if (models.state === 'ready') {
    const count = models.list.length
    return (
      <p className="flex items-center gap-1.5 text-[12.5px] text-ok">
        <CheckCircle2 size={13} /> {count ? `Connected. ${count} model${count > 1 ? 's' : ''} available.` : 'Connected, but it lists no models. Type a name above.'}
      </p>
    )
  }
  return null
}

// --- answers and documents ------------------------------------------------------

const KNOWLEDGE = [
  {
    title: 'Answers',
    fields: [
      { key: 'retrieval_k', label: 'Passages per answer', help: 'How much of your documents the model reads for each question. More is thorough, fewer is faster and cheaper.', min: 1, max: 50, slider: true },
      { key: 'llm_thinking', label: 'Deep thinking', help: 'Lets models that support it reason before answering. Better on hard questions, but answers can take a minute or more.', toggle: true },
      { key: 'chat_history_messages', label: 'Conversation memory', help: 'How many earlier messages the model sees, so follow-up questions make sense.', min: 0, max: 100, slider: true, unit: 'messages' },
    ],
  },
  {
    title: 'Documents',
    note: 'Passage sizes apply to documents indexed from now on.',
    fields: [
      { key: 'chunk_size', label: 'Passage size', help: 'How much text goes into each searchable passage.', min: 1, unit: 'characters' },
      { key: 'chunk_overlap', label: 'Passage overlap', help: 'Text shared between neighbouring passages, so a sentence is not cut in two.', min: 0, unit: 'characters' },
      { key: 'max_upload_mb', label: 'Largest upload', help: 'The biggest single file anyone can add.', min: 1, unit: 'MB' },
    ],
  },
]
const ALL_FIELDS = KNOWLEDGE.flatMap((group) => group.fields)

function fieldError(field, form) {
  if (field.toggle) return ''
  const value = form[field.key]
  if (value === '' || value === null) return 'Enter a number.'
  if (!Number.isInteger(value)) return 'Enter a whole number.'
  if (value < field.min) return `Must be ${field.min} or more.`
  if (field.max !== undefined && value > field.max) return `Must be ${field.max} or less.`
  if (field.key === 'chunk_overlap' && value >= form.chunk_size) return 'Must be smaller than the passage size.'
  return ''
}

function Knowledge() {
  const toast = useToast()
  const settings = useLoad(() => api.settings(), [])
  const [form, setForm] = useState(null)
  const [serverErrors, setServerErrors] = useState({})
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    if (settings.data) setForm(settings.data.values)
  }, [settings.data])

  if (settings.error) return <Page><ErrorState error={settings.error} onRetry={settings.reload} /></Page>
  if (!form) return <Page><Card><SkeletonRows rows={4} className="h-14" /></Card></Page>

  const saved = settings.data.values
  const changes = Object.fromEntries(ALL_FIELDS.filter((f) => form[f.key] !== saved[f.key]).map((f) => [f.key, form[f.key]]))
  const dirty = Object.keys(changes).length > 0
  const errors = Object.fromEntries(ALL_FIELDS.map((f) => [f.key, fieldError(f, form) || serverErrors[f.key]]))
  const valid = !Object.values(errors).some(Boolean)
  const set = (key, raw) => {
    setServerErrors({})
    setForm((f) => ({ ...f, [key]: typeof raw === 'boolean' || raw === '' ? raw : Number(raw) }))
  }
  const save = async () => {
    setBusy(true)
    try {
      await api.saveSettings({ values: changes })
      await settings.reload()
      toast.ok('Settings saved')
    } catch (e) {
      const fields = Object.fromEntries((e.fields || []).map((f) => [f.field, f.message]))
      if (Object.keys(fields).length) setServerErrors(fields)
      else toast.error(e)
    } finally {
      setBusy(false)
    }
  }

  return (
    <Page>
      <PageHeader description="Sensible defaults work for most teams. Tune these if answers miss things or feel slow." />
      <div className="space-y-4 pb-20">
        {KNOWLEDGE.map((group) => (
          <Card key={group.title}>
            <div className="border-b border-line px-5 py-3.5">
              <h2 className="font-serif text-xl leading-tight">{group.title}</h2>
              {group.note && <p className="mt-0.5 text-[12.5px] text-muted">{group.note}</p>}
            </div>
            <div className="divide-y divide-line">
              {group.fields.map((field) => (
                field.toggle ? (
                  <ToggleSetting key={field.key} field={field} value={form[field.key]} onChange={(v) => set(field.key, v)} />
                ) : (
                  <NumberSetting key={field.key} field={field} value={form[field.key]} error={errors[field.key]} onChange={(v) => set(field.key, v)} />
                )
              ))}
            </div>
          </Card>
        ))}
      </div>
      {dirty && (
        <div className="animate-rise sticky bottom-4 z-10 flex items-center justify-between gap-3 rounded-xl border border-line bg-surface/95 p-2.5 pl-4 shadow-float backdrop-blur">
          <span className="truncate text-[13px] text-muted">{valid ? 'Unsaved changes' : 'Fix the highlighted settings'}</span>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => { setForm(saved); setServerErrors({}) }}>Discard</Button>
            <Button variant="primary" busy={busy} disabled={!valid} onClick={save}>Save changes</Button>
          </div>
        </div>
      )}
    </Page>
  )
}

function ToggleSetting({ field, value, onChange }) {
  return (
    <div className="flex items-center justify-between gap-6 px-5 py-4">
      <div>
        <p className="font-medium">{field.label}</p>
        <p className="text-[13px] text-muted">{field.help}</p>
      </div>
      <button
        type="button"
        role="switch"
        aria-checked={Boolean(value)}
        aria-label={field.label}
        onClick={() => onChange(!value)}
        className={cx('relative h-6 w-11 shrink-0 rounded-full transition', value ? 'bg-accent' : 'bg-line-strong')}
      >
        <span className={cx('absolute left-0.5 top-0.5 size-5 rounded-full bg-surface shadow-sm transition-transform', value && 'translate-x-5')} />
      </button>
    </div>
  )
}

function NumberSetting({ field, value, error, onChange }) {
  const id = `setting-${field.key}`
  return (
    <div className="grid gap-3 px-5 py-4 sm:grid-cols-[minmax(0,1fr)_230px] sm:items-center sm:gap-6">
      <div>
        <label htmlFor={id} className="font-medium">{field.label}</label>
        <p className="text-[13px] text-muted">{field.help}</p>
      </div>
      <div>
        <div className="flex items-center gap-2.5">
          {field.slider && (
            <input
              type="range"
              aria-label={`${field.label} slider`}
              className="min-w-0 flex-1 accent-[var(--accent)]"
              min={field.min}
              max={field.max}
              value={value === '' ? field.min : value}
              onChange={(e) => onChange(e.target.value)}
            />
          )}
          <div className={cx('relative', field.slider ? 'w-[72px] shrink-0' : 'w-full')}>
            <input
              id={id}
              type="number"
              inputMode="numeric"
              aria-invalid={Boolean(error)}
              min={field.min}
              max={field.max}
              value={value}
              onChange={(e) => onChange(e.target.value)}
              className={cx(inputClass, 'h-9 tabular-nums', !field.slider && field.unit && 'pr-24', error && 'border-bad focus:border-bad focus:ring-bad/20')}
            />
            {!field.slider && field.unit && (
              <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-xs text-faint">{field.unit}</span>
            )}
          </div>
        </div>
        {error && <p role="alert" className="mt-1.5 text-[12.5px] text-bad">{error}</p>}
      </div>
    </div>
  )
}
