type Props = {
  loading?: boolean
  error?: string | null
  empty?: string | null
  className?: string
}

export function StatusLine({ loading, error, empty, className = '' }: Props) {
  const base = ['font-mono text-sm', className].filter(Boolean).join(' ')
  if (loading) {
    return <p className={`${base} text-muted`}>Loading…</p>
  }
  if (error) {
    return <p className={`${base} text-danger`}>{error}</p>
  }
  if (empty) {
    return <p className={`${base} text-muted`}>{empty}</p>
  }
  return null
}
