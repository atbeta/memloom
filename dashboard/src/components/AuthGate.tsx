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
    <div className="flex min-h-full items-center justify-center p-6 md:p-10">
      <form onSubmit={onSubmit} className="panel w-full max-w-md p-7 md:p-8">
        <p className="font-mono text-[11px] tracking-[0.2em] text-accent uppercase">memloom</p>
        <h1 className="mt-3 text-2xl font-semibold tracking-tight">Admin access</h1>
        <p className="mt-3 text-sm leading-relaxed text-muted">
          Enter the Bearer key used by <code className="font-mono text-ink">memloom serve</code>
          {' '}(<code className="font-mono text-ink">MEMLOOM_ADMIN_KEY</code> or{' '}
          <code className="font-mono text-ink">MEMLOOM_INGEST_KEY</code>). Stored in sessionStorage only.
        </p>
        <label className="mt-6 block text-sm font-medium" htmlFor="api-key">
          API key
        </label>
        <input
          id="api-key"
          type="password"
          autoComplete="off"
          value={key}
          onChange={(e) => setLocalKey(e.target.value)}
          className="field mt-2 font-mono"
          placeholder="memloom_ingest_…"
        />
        <button type="submit" className="btn btn-primary mt-5 w-full">
          Continue
        </button>
      </form>
    </div>
  )
}
