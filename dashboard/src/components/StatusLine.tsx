type Props = {
  loading?: boolean
  error?: string | null
  empty?: string | null
}

export function StatusLine({ loading, error, empty }: Props) {
  if (loading) {
    return <p className="font-mono text-sm text-muted">Loading…</p>
  }
  if (error) {
    return <p className="font-mono text-sm text-danger">{error}</p>
  }
  if (empty) {
    return <p className="font-mono text-sm text-muted">{empty}</p>
  }
  return null
}
