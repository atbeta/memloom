import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiGet, type Overview as OverviewData } from '@/lib/api'
import { formatTs } from '@/lib/format'
import { StatusLine } from '@/components/StatusLine'

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const body = await apiGet<OverviewData>('/api/admin/overview')
        if (!cancelled) {
          setData(body)
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

  if (loading || error || !data) {
    return <StatusLine loading={loading} error={error} />
  }

  const sources = Object.entries(data.by_source)

  return (
    <div className="space-y-6">
      <section>
        <h2 className="text-sm font-medium text-muted">Store</h2>
        <div className="mt-2 grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="records" value={String(data.total)} />
          <Stat label="vectors" value={String(data.vectors)} />
          <Stat label="agents" value={String(data.agent_count)} />
          <Stat label="hosts" value={String(data.host_count)} />
        </div>
        <dl className="mt-3 grid gap-1 font-mono text-xs text-muted md:grid-cols-2">
          <div>
            <dt className="inline text-ink">data_root </dt>
            <dd className="inline">{data.data_root}</dd>
          </div>
          <div>
            <dt className="inline text-ink">embed </dt>
            <dd className="inline">{data.embed_enabled ? 'enabled' : 'disabled'}</dd>
          </div>
        </dl>
      </section>

      <section>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium text-muted">By source</h2>
          <Link to="/explorer" className="text-sm text-accent hover:underline">
            Search →
          </Link>
        </div>
        {sources.length === 0 ? (
          <StatusLine empty="No records yet." />
        ) : (
          <table className="mt-2 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="py-1.5 font-medium">source</th>
                <th className="py-1.5 text-right font-medium">count</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(([source, count]) => (
                <tr key={source} className="border-b border-line/70">
                  <td className="py-1.5 font-mono">{source}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section>
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="text-sm font-medium text-muted">Recent runs</h2>
          <Link to="/pipeline" className="text-sm text-accent hover:underline">
            All runs →
          </Link>
        </div>
        {data.runs.length === 0 ? (
          <StatusLine empty="No collector runs recorded." />
        ) : (
          <table className="mt-2 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="py-1.5 font-medium">started</th>
                <th className="py-1.5 font-medium">source</th>
                <th className="py-1.5 font-medium">host</th>
                <th className="py-1.5 text-right font-medium">new</th>
                <th className="py-1.5 text-right font-medium">dup</th>
                <th className="py-1.5 text-right font-medium">err</th>
              </tr>
            </thead>
            <tbody>
              {data.runs.slice(0, 8).map((r) => (
                <tr key={r.run_id} className="border-b border-line/70">
                  <td className="py-1.5 font-mono text-xs">{formatTs(r.started_at)}</td>
                  <td className="py-1.5 font-mono">{r.source}</td>
                  <td className="py-1.5 font-mono">{r.host}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{r.new_records}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{r.duplicates}</td>
                  <td className="py-1.5 text-right font-mono tabular-nums">{r.errors.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="border border-line bg-panel px-3 py-3">
      <div className="font-mono text-2xl font-medium tabular-nums tracking-tight">{value}</div>
      <div className="mt-1 text-xs uppercase tracking-wide text-muted">{label}</div>
    </div>
  )
}
