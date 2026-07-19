import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { ApiError, apiGet, apiSend, type Overview as OverviewData } from '@/lib/api'
import { formatTs } from '@/lib/format'
import { StatusLine } from '@/components/StatusLine'

export default function Overview() {
  const [data, setData] = useState<OverviewData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [embedding, setEmbedding] = useState(false)
  const [notice, setNotice] = useState<string | null>(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const body = await apiGet<OverviewData>('/api/admin/overview')
      setData(body)
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        window.location.reload()
        return
      }
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void load()
  }, [load])

  async function runEmbed() {
    setEmbedding(true)
    setNotice(null)
    setError(null)
    try {
      const body = await apiSend<{ ok: boolean; embedded: number; skipped: number; errors: string[] }>(
        'POST',
        '/api/admin/actions/embed',
        { limit: 200, force: false },
      )
      setNotice(
        `Embed finished — embedded ${body.embedded}, skipped ${body.skipped}, errors ${body.errors.length}.`,
      )
      await load()
    } catch (e) {
      if (e instanceof ApiError && e.status === 401) {
        window.location.reload()
        return
      }
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setEmbedding(false)
    }
  }

  if (loading || !data) {
    return <StatusLine loading={loading} error={error} className="py-2" />
  }

  const sources = Object.entries(data.by_source)

  return (
    <div className="space-y-6">
      {error ? <StatusLine error={error} /> : null}
      {notice ? <p className="font-mono text-sm text-accent">{notice}</p> : null}

      <section className="panel panel-pad space-y-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <h2 className="section-title">Store</h2>
          <button
            type="button"
            onClick={() => void runEmbed()}
            disabled={embedding || !data.embed_enabled}
            className="btn btn-primary"
            title={data.embed_enabled ? 'Backfill up to 200 missing vectors' : 'Enable embed in Settings'}
          >
            {embedding ? 'Embedding…' : 'Embed backfill'}
          </button>
        </div>
        <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
          <Stat label="records" value={String(data.total)} />
          <Stat label="vectors" value={String(data.vectors)} />
          <Stat label="agents" value={String(data.agent_count)} />
          <Stat label="hosts" value={String(data.host_count)} />
        </div>
        <dl className="grid gap-2 font-mono text-xs text-muted md:grid-cols-2">
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

      <section className="panel panel-pad">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="section-title">By source</h2>
          <Link to="/explorer" className="text-sm text-accent hover:underline">
            Search →
          </Link>
        </div>
        {sources.length === 0 ? (
          <StatusLine empty="No records yet." className="mt-4" />
        ) : (
          <table className="mt-4 w-full border-collapse text-sm">
            <thead>
              <tr className="border-b border-line text-left text-muted">
                <th className="pb-2 font-medium">source</th>
                <th className="pb-2 text-right font-medium">count</th>
              </tr>
            </thead>
            <tbody>
              {sources.map(([source, count]) => (
                <tr key={source} className="border-b border-line/70">
                  <td className="py-2.5 font-mono">{source}</td>
                  <td className="py-2.5 text-right font-mono tabular-nums">{count}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      <section className="panel panel-pad">
        <div className="flex items-baseline justify-between gap-3">
          <h2 className="section-title">Recent runs</h2>
          <Link to="/pipeline" className="text-sm text-accent hover:underline">
            All runs →
          </Link>
        </div>
        {data.runs.length === 0 ? (
          <StatusLine empty="No collector runs recorded." className="mt-4" />
        ) : (
          <div className="mt-4 overflow-x-auto">
            <table className="w-full min-w-[560px] border-collapse text-sm">
              <thead>
                <tr className="border-b border-line text-left text-muted">
                  <th className="pb-2 font-medium">started</th>
                  <th className="pb-2 font-medium">source</th>
                  <th className="pb-2 font-medium">host</th>
                  <th className="pb-2 text-right font-medium">new</th>
                  <th className="pb-2 text-right font-medium">dup</th>
                  <th className="pb-2 text-right font-medium">err</th>
                </tr>
              </thead>
              <tbody>
                {data.runs.slice(0, 8).map((r) => (
                  <tr key={r.run_id} className="border-b border-line/70">
                    <td className="py-2.5 font-mono text-xs">{formatTs(r.started_at)}</td>
                    <td className="py-2.5 font-mono">{r.source}</td>
                    <td className="py-2.5 font-mono">{r.host}</td>
                    <td className="py-2.5 text-right font-mono tabular-nums">{r.new_records}</td>
                    <td className="py-2.5 text-right font-mono tabular-nums">{r.duplicates}</td>
                    <td className="py-2.5 text-right font-mono tabular-nums">{r.errors.length}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-md border border-line bg-surface px-3.5 py-3.5">
      <div className="font-mono text-2xl font-medium tabular-nums tracking-tight">{value}</div>
      <div className="mt-1.5 text-[11px] uppercase tracking-wide text-muted">{label}</div>
    </div>
  )
}
