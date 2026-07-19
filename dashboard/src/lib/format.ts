export function formatTs(ms: number | null | undefined): string {
  if (!ms) return '—'
  try {
    return new Date(ms).toLocaleString()
  } catch {
    return String(ms)
  }
}

export function formatDuration(started: number, finished: number | null | undefined): string {
  if (!started || !finished) return '—'
  const ms = finished - started
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(1)}s`
}
