import { useState, type FormEvent, type ReactNode } from 'react'
import { getKey, setKey } from '@/lib/api'

type Props = {
  children: ReactNode
}

export function AuthGate({ children }: Props) {
  const [key, setLocalKey] = useState(getKey() ?? '')
  const [authed, setAuthed] = useState(Boolean(getKey()))

  function onSubmit(e: FormEvent) {
    e.preventDefault()
    const trimmed = key.trim()
    if (!trimmed) return
    setKey(trimmed)
    setAuthed(true)
  }

  if (authed) return <>{children}</>

  return (
    <div className="flex min-h-full items-center justify-center p-6">
      <form
        onSubmit={onSubmit}
        className="w-full max-w-md border border-line bg-panel p-6"
      >
        <p className="font-mono text-sm tracking-wide text-accent">memloom</p>
        <h1 className="mt-2 text-2xl font-semibold tracking-tight">Admin access</h1>
        <p className="mt-2 text-sm text-muted">
          Enter the Bearer key used by <code className="font-mono">memloom serve</code>
          {' '}(<code className="font-mono">MEMLOOM_ADMIN_KEY</code> or{' '}
          <code className="font-mono">MEMLOOM_INGEST_KEY</code>). Stored in sessionStorage only.
        </p>
        <label className="mt-5 block text-sm font-medium" htmlFor="api-key">
          API key
        </label>
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => setLocalKey(e.target.value)}
          className="mt-1 w-full border border-line bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
          placeholder="memloom_ingest_…"
        />
        <button
          type="submit"
          className="mt-4 w-full bg-ink px-3 py-2 text-sm font-medium text-white hover:bg-accent"
        >
          Continue
        </button>
      </form>
    </div>
  )
}
