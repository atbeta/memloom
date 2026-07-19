import { useEffect, useState } from 'react'
import { ApiError, apiGet, apiSend, type RunRow } from '@/lib/api'
import { formatDuration, formatTs } from '@/lib/format'
import { StatusLine } from '@/components/StatusLine'

export default function Pipeline() {
  const [runs, setRuns] = useState<RunRow[]>([])
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [collecting, setCollecting] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const body = await apiGet<RunRow[]>('/api/admin/runs', { limit: 100 })
      setRuns(body)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        window.location.reload()
        return
      }
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    void load()
  }, [])

  async function runCollect() {
    setCollecting(true)
    setNotice(null)
    setError(null)
    try {
      const body = await apiSend<{ ok: boolean; runs: RunRow[] }>(
        'POST',
        '/api/admin/actions/collect',
        {},
      )
      const n = body.runs.reduce((acc, r) => acc + (r.new_records || 0), 0)
      setNotice(`Collect finished — ${body.runs.length} source(s), ${n} new record(s).`)
      await load()
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        window.location.reload()
        return
      }
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setCollecting(false)
    }
  }

  return (
    <div className="space-y-5">
      <div className="panel panel-pad flex flex-wrap items-end justify-between gap-4">
        <div className="space-y-1.5">
          <h2 className="section-title">Collector runs</h2>
          <p className="text-sm text-muted">Trigger one collect pass (same as CLI).</p>
        </div>
        <button
          type="button"
          onClick={() => void runCollect()}
          disabled={collecting}
          className="btn btn-primary"
        >
          {collecting ? 'Collecting…' : 'Run collect'}
        </button>
      </div>

      <StatusLine loading={loading && runs.length === 0} error={error} />
      {notice ? <p className="font-mono text-sm text-accent">{notice}</p> : null}

      {!loading && runs.length === 0 ? (
        <div className="panel panel-pad">
          <StatusLine empty="No collector runs yet. Run collect above or `memloom collect`." />
        </div>
      ) : runs.length > 0 ? (
        <div className="panel overflow-x-auto">
          <table className="w-full min-w-[720px] border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="px-4 py-3 font-medium">started</th>
                <th className="px-4 py-3 font-medium">source</th>
                <th className="px-4 py-3 font-medium">host</th>
                <th className="px-4 py-3 text-right font-medium">discovered</th>
                <th className="px-4 py-3 text-right font-medium">new</th>
                <th className="px-4 py-3 text-right font-medium">dup</th>
                <th className="px-4 py-3 text-right font-medium">filtered</th>
                <th className="px-4 py-3 text-right font-medium">errors</th>
                <th className="px-4 py-3 text-right font-medium">duration</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={r.run_id} className="border-b border-line/70 align-top">
                  <td className="px-4 py-3 font-mono text-xs">{formatTs(r.started_at)}</td>
                  <td className="px-4 py-3 font-mono">{r.source}</td>
                  <td className="px-4 py-3 font-mono">{r.host}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">{r.discovered}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">{r.new_records}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">{r.duplicates}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">{r.filtered}</td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {r.errors.length}
                    {r.errors.length > 0 ? (
                      <details className="mt-1.5 text-left text-[11px] text-danger">
                        <summary className="cursor-pointer">details</summary>
                        <ul className="mt-1 list-disc pl-4">
                          {r.errors.slice(0, 5).map((err, i) => (
                            <li key={i}>{err}</li>
                          ))}
                        </ul>
                      </details>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-right font-mono tabular-nums">
                    {formatDuration(r.started_at, r.finished_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  )
}
