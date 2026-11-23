import { useState } from 'react'
import { ArrowRight, Check } from 'lucide-react'
import { api } from '../lib/api.js'
import { useLoad } from '../lib/hooks.js'
import { navigate, projectHref } from '../lib/router.js'
import { Button, Card, cx, ErrorState, Spinner, TextField, useToast, Wordmark } from '../ui/index.jsx'
import { ModelEditor } from './Settings.jsx'

const STEPS = [
  { key: 'chat', label: 'Chat', title: 'Connect a chat model', blurb: 'This is the model that reads your documents and writes the answers.' },
  { key: 'embedding', label: 'Search', title: 'Connect an embedding model', blurb: 'This makes your documents searchable by meaning. It can be a different provider.' },
  { key: 'project', label: 'Project', title: 'Name your first project', blurb: 'A project holds a set of documents and the people who can ask them questions.' },
]

/** First run, straight after the owner account is created. */
export default function Onboarding() {
  const settings = useLoad(() => api.settings(), [])
  const providers = useLoad(() => api.providers(), [])
  const [index, setIndex] = useState(0)
  const step = STEPS[index]
  const next = () => setIndex((i) => i + 1)

  const chatProvider = settings.data?.values.llm_provider
  const reusable = providers.data?.find((p) => p.key === chatProvider)?.supports_embeddings

  return (
    <div className="flex h-dvh flex-col overflow-y-auto">
      <header className="flex shrink-0 items-center justify-between gap-4 px-5 py-4 sm:px-8">
        <Wordmark />
        <ol className="flex items-center gap-1.5 sm:gap-2" aria-label="Setup progress">
          {STEPS.map((s, i) => (
            <li key={s.key} aria-current={i === index ? 'step' : undefined} className="flex items-center gap-1.5 sm:gap-2">
              {i > 0 && <span className={cx('h-px w-4 sm:w-8', i <= index ? 'bg-accent' : 'bg-line-strong')} />}
              <span className={cx(
                'grid size-6 place-items-center rounded-full text-xs font-medium transition',
                i < index ? 'bg-accent text-on-accent' : i === index ? 'border border-accent text-accent' : 'border border-line-strong text-faint',
              )}>
                {i < index ? <Check size={13} /> : i + 1}
              </span>
              <span className={cx('hidden text-[13px] md:block', i === index ? 'font-medium' : 'text-muted')}>{s.label}</span>
            </li>
          ))}
        </ol>
      </header>
      <main className="mx-auto w-full max-w-2xl flex-1 px-4 pt-4 pb-16 sm:pt-8">
        <div key={step.key} className="animate-rise">
          <h1 className="font-serif text-[34px] leading-tight tracking-tight">{step.title}</h1>
          <p className="mt-1.5 mb-6 text-[15px] text-muted">{step.blurb}</p>
          {settings.error ? (
            <ErrorState error={settings.error} onRetry={settings.reload} />
          ) : !settings.data || !providers.data ? (
            <div className="grid h-48 place-items-center text-muted"><Spinner size={22} /></div>
          ) : step.key === 'project' ? (
            <FirstProject />
          ) : (
            <Card className="p-4 sm:p-5">
              <ModelEditor
                key={step.key}
                kind={step.key}
                settings={settings.data}
                providers={providers.data}
                initialProvider={step.key === 'embedding' && reusable ? chatProvider : undefined}
                autoConfirm
                saveLabel="Save and continue"
                onSkip={next}
                onSaved={async () => {
                  await settings.reload()
                  next()
                }}
              />
            </Card>
          )}
        </div>
      </main>
    </div>
  )
}

function FirstProject() {
  const toast = useToast()
  const [name, setName] = useState('')
  const [busy, setBusy] = useState(false)
  const submit = async (event) => {
    event.preventDefault()
    setBusy(true)
    try {
      const project = await api.createProject(name.trim())
      navigate(projectHref(project.id, 'documents'), { replace: true })
    } catch (e) {
      toast.error(e)
      setBusy(false)
    }
  }
  return (
    <Card className="p-4 sm:p-5">
      <form onSubmit={submit} className="space-y-4">
        <TextField label="Project name" autoFocus required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} placeholder="Legal, Engineering, Research…" />
        <div className="flex items-center justify-end gap-2 border-t border-line pt-4">
          <Button variant="ghost" onClick={() => navigate('#/', { replace: true })}>Skip for now</Button>
          <Button type="submit" variant="primary" busy={busy} disabled={!name.trim()}>
            Create and add documents {!busy && <ArrowRight size={16} />}
          </Button>
        </div>
      </form>
    </Card>
  )
}
