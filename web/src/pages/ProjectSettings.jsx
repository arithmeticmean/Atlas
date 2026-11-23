import { useState } from 'react'
import { api } from '../lib/api.js'
import { Button, Card, Page, PageHeader, TextField, useToast } from '../ui/index.jsx'
import { useWorkspace } from './Shell.jsx'

export default function ProjectSettings() {
  const { project, setProjects, reloadProjects } = useWorkspace()
  const toast = useToast()
  const [name, setName] = useState(project.name)
  const [confirmName, setConfirmName] = useState('')
  const [busy, setBusy] = useState('')

  const rename = async (event) => {
    event.preventDefault()
    setBusy('rename')
    try {
      await api.renameProject(project.id, name.trim())
      await reloadProjects()
      toast.ok('Project renamed')
    } catch (e) {
      toast.error(e)
    } finally {
      setBusy('')
    }
  }
  const destroy = async (event) => {
    event.preventDefault()
    setBusy('delete')
    try {
      await api.deleteProject(project.id)
      setProjects((all) => all.filter((p) => p.id !== project.id)) // the shell redirects
      toast.ok('Project deleted')
    } catch (e) {
      toast.error(e)
      setBusy('')
    }
  }
  return (
    <Page>
      <PageHeader title="Project settings" />
      <div className="space-y-5">
        <Card className="p-5">
          <form onSubmit={rename} className="flex items-end gap-2">
            <TextField label="Project name" className="flex-1" required maxLength={200} value={name} onChange={(e) => setName(e.target.value)} />
            <Button type="submit" variant="primary" className="h-10" busy={busy === 'rename'} disabled={!name.trim() || name === project.name}>Save</Button>
          </form>
        </Card>
        <Card className="border-bad/40 p-5">
          <h2 className="font-serif text-xl text-bad">Delete project</h2>
          <p className="mt-1 mb-4 text-muted">Permanently removes its documents, search index, chats and connectors. This can't be undone.</p>
          <form onSubmit={destroy} className="flex items-end gap-2">
            <TextField label={`Type “${project.name}” to confirm`} className="flex-1" autoComplete="off" value={confirmName} onChange={(e) => setConfirmName(e.target.value)} />
            <Button type="submit" variant="danger" className="h-10" busy={busy === 'delete'} disabled={confirmName !== project.name}>Delete</Button>
          </form>
        </Card>
      </div>
    </Page>
  )
}
