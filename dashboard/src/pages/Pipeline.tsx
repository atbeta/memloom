import { useEffect, useState } from 'react'
import { ApiError, apiGet, type RunRow } from '@/lib/api'
import { formatDuration, formatTs } from '@/lib/format'
import { StatusLine } from '@/components/StatusLine'

export default function Pipeline() {
  const [runs, setRuns] = useState<RunRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const body = await apiGet<RunRow[]>('/api/admin/runs', { limit: 100 })
        if (!cancelled) {
          setRuns(body)
          setError(null)
        }
      } catch (e) {
        if (!cancelled) {
          if (e instanceof ApiError && e.status === 401) {
            window.location.reload()
            return
          }
          setError(e instanceof Error ? e.message : String(e))
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  if (loading || error) {
    return <StatusLine loading={loading} error={error} />
  }

  if (runs.length === 0) {
    return <StatusLine empty="No collector runs yet. Run `memloom collect`." />
  }

  return (
    <div>
      <h2 className="text-sm font-medium text-muted">Collector runs</h2>
      <div className="mt-2 overflow-x-auto border border-line bg-panel">
        <table className="w-full min-w-[720px] border-collapse text-sm">
          <thead>
            <tr className="border-b border-line text-left text-muted">
              <th className="px-3 py-2 font-medium">started</th>
              <th className="px-3 py-2 font-medium">source</th>
              <th className="px-3 py-2 font-medium">host</th>
              <th className="px-3 py-2 text-right font-medium">discovered</th>
              <th className="px-3 py-2 text-right font-medium">new</th>
              <th className="px-3 py-2 text-right font-medium">dup</th>
              <th className="px-3 py-2 text-right font-medium">filtered</th>
              <th className="px-3 py-2 text-right font-medium">errors</th>
              <th className="px-3 py-2 text-right font-medium">duration</th>
            </tr>
          </thead>
          <tbody>
            {runs.map((r) => (
              <tr key={r.run_id} className="border-b border-line/70 align-top">
                <td className="px-3 py-2 font-mono text-xs">{formatTs(r.started_at)}</td>
                <td className="px-3 py-2 font-mono">{r.source}</td>
                <td className="px-3 py-2 font-mono">{r.host}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{r.discovered}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{r.new_records}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{r.duplicates}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">{r.filtered}</td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {r.errors.length}
                  {r.errors.length > 0 ? (
                    <details className="mt-1 text-left text-[11px] text-danger">
                      <summary className="cursor-pointer">details</summary>
                      <ul className="mt-1 list-disc pl-4">
                        {r.errors.slice(0, 5).map((err, i) => (
                          <li key={i}>{err}</li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </td>
                <td className="px-3 py-2 text-right font-mono tabular-nums">
                  {formatDuration(r.started_at, r.finished_at)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
