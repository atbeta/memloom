import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  apiGet,
  apiSend,
  type QuarantineItem,
  type RecordDetail,
  type SearchHit,
} from '@/lib/api'
import { formatTs } from '@/lib/format'
import { StatusLine } from '@/components/StatusLine'

export default function Explorer() {
  const [q, setQ] = useState('')
  const [source, setSource] = useState('')
  const [hybrid, setHybrid] = useState(true)
  const [hits, setHits] = useState<SearchHit[]>([])
  const [selected, setSelected] = useState<RecordDetail | null>(null)
  const [view, setView] = useState<'markdown' | 'json'>('markdown')
  const [loading, setLoading] = useState(false)
  const [detailLoading, setDetailLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [quarantine, setQuarantine] = useState<QuarantineItem[]>([])
  const [busyId, setBusyId] = useState<string | null>(null)

  async function loadQuarantine() {
    try {
      setQuarantine(await apiGet<QuarantineItem[]>('/api/admin/quarantine'))
    } catch {
      /* ignore list errors in this panel */
    }
  }

  useEffect(() => {
    void loadQuarantine()
  }, [])

  async function onSearch(e?: FormEvent) {
    e?.preventDefault()
    if (!q.trim()) return
    setLoading(true)
    setError(null)
    setSelected(null)
    try {
      const body = await apiGet<SearchHit[]>('/api/admin/search', {
        q: q.trim(),
        source: source.trim() || undefined,
        hybrid,
        limit: 40,
      })
      setHits(body)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.reload()
        return
      }
      setError(err instanceof Error ? err.message : String(err))
      setHits([])
    } finally {
      setLoading(false)
    }
  }

  async function openRecord(id: string) {
    setDetailLoading(true)
    setError(null)
    try {
      const body = await apiGet<RecordDetail>(`/api/admin/records/${id}`)
      setSelected(body)
      setView('markdown')
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.reload()
        return
      }
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setDetailLoading(false)
    }
  }

  async function quarantineSelected() {
    if (!selected) return
    setBusyId(selected.id)
    setNotice(null)
    setError(null)
    try {
      const body = await apiSend<{ moved: string[] }>('POST', '/api/admin/quarantine/add', {
        record_ids: [selected.id],
        reason: 'dashboard',
      })
      setNotice(`Quarantined ${body.moved.length} record(s).`)
      setHits((prev) => prev.filter((h) => h.id !== selected.id))
      setSelected(null)
      await loadQuarantine()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.reload()
        return
      }
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  async function restoreQuarantined(id: string) {
    setBusyId(id)
    setNotice(null)
    setError(null)
    try {
      const body = await apiSend<{ moved: string[] }>('POST', '/api/admin/quarantine/restore', {
        record_ids: [id],
      })
      setNotice(`Restored ${body.moved.length} record(s).`)
      await loadQuarantine()
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.reload()
        return
      }
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div className="space-y-4">
      {notice ? <p className="font-mono text-sm text-accent">{notice}</p> : null}
    <div className="flex min-h-[70vh] flex-col gap-4 lg:flex-row">
      <section className="flex w-full flex-col lg:w-[42%]">
        <form onSubmit={onSearch} className="space-y-2 border border-line bg-panel p-3">
          <div className="flex gap-2">
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder="FTS5 / hybrid query"
              className="min-w-0 flex-1 border border-line bg-surface px-3 py-2 font-mono text-sm outline-none focus:border-accent"
            />
            <button
              type="submit"
              className="bg-ink px-3 py-2 text-sm font-medium text-white hover:bg-accent"
            >
              Search
            </button>
          </div>
          <div className="flex flex-wrap items-center gap-3 text-sm">
            <label className="flex items-center gap-1.5">
              <span className="text-muted">source</span>
              <input
                value={source}
                onChange={(e) => setSource(e.target.value)}
                placeholder="optional"
                className="w-36 border border-line bg-surface px-2 py-1 font-mono text-xs outline-none focus:border-accent"
              />
            </label>
            <label className="flex items-center gap-1.5 text-muted">
              <input
                type="checkbox"
                checked={hybrid}
                onChange={(e) => setHybrid(e.target.checked)}
              />
              hybrid
            </label>
          </div>
        </form>

        <div className="mt-3 min-h-0 flex-1 overflow-auto border border-line bg-panel">
          <StatusLine
            loading={loading}
            error={error && !selected ? error : null}
            empty={!loading && !error && hits.length === 0 ? 'No results.' : null}
          />
          <ul className="divide-y divide-line">
            {hits.map((h) => (
              <li key={h.id}>
                <button
                  type="button"
                  onClick={() => openRecord(h.id)}
                  className={[
                    'block w-full px-3 py-2 text-left hover:bg-accent-soft',
                    selected?.id === h.id ? 'bg-accent-soft' : '',
                  ].join(' ')}
                >
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="font-mono text-xs text-accent">{h.source}</span>
                    <span className="font-mono text-[11px] text-muted">{formatTs(h.captured_at)}</span>
                  </div>
                  <p className="mt-1 line-clamp-2 text-sm">{h.content || '(empty snippet)'}</p>
                  <p className="mt-1 truncate font-mono text-[11px] text-muted">{h.id}</p>
                </button>
              </li>
            ))}
          </ul>
        </div>
      </section>

      <section className="flex min-h-[50vh] flex-1 flex-col border border-line bg-panel">
        {!selected && !detailLoading ? (
          <div className="flex flex-1 items-center justify-center p-6">
            <StatusLine empty="Select a result to inspect the raw record." />
          </div>
        ) : detailLoading ? (
          <div className="p-4">
            <StatusLine loading />
          </div>
        ) : selected ? (
          <>
            <div className="flex flex-wrap items-center justify-between gap-2 border-b border-line px-3 py-2">
              <div className="min-w-0">
                <p className="truncate font-mono text-xs text-muted">{selected.id}</p>
                <p className="truncate text-sm">
                  <span className="font-mono text-accent">{selected.source}</span>
                  <span className="text-muted"> · {selected.role}</span>
                  {selected.project ? (
                    <span className="text-muted"> · {selected.project}</span>
                  ) : null}
                </p>
              </div>
              <div className="flex flex-wrap gap-1 text-sm">
                <button
                  type="button"
                  onClick={() => setView('markdown')}
                  className={
                    view === 'markdown'
                      ? 'bg-accent-soft px-2 py-1 text-accent'
                      : 'px-2 py-1 text-muted hover:text-ink'
                  }
                >
                  Markdown
                </button>
                <button
                  type="button"
                  onClick={() => setView('json')}
                  className={
                    view === 'json'
                      ? 'bg-accent-soft px-2 py-1 text-accent'
                      : 'px-2 py-1 text-muted hover:text-ink'
                  }
                >
                  JSON
                </button>
                <button
                  type="button"
                  onClick={() => void quarantineSelected()}
                  disabled={busyId === selected.id}
                  className="px-2 py-1 text-danger hover:bg-surface disabled:opacity-40"
                >
                  Quarantine
                </button>
              </div>
            </div>
            <pre className="min-h-0 flex-1 overflow-auto p-3 font-mono text-xs leading-relaxed whitespace-pre-wrap">
              {view === 'markdown'
                ? selected.markdown || '(empty markdown)'
                : JSON.stringify(selected.record, null, 2)}
            </pre>
          </>
        ) : null}
      </section>
    </div>

      <section className="border border-line bg-panel p-3">
        <h2 className="text-sm font-medium text-muted">Quarantine</h2>
        {quarantine.length === 0 ? (
          <p className="mt-2 font-mono text-sm text-muted">Empty.</p>
        ) : (
          <ul className="mt-2 divide-y divide-line">
            {quarantine.map((item) => (
              <li key={item.id} className="flex items-center justify-between gap-3 py-2 text-sm">
                <div className="min-w-0">
                  <p className="truncate font-mono text-xs text-accent">{item.source}</p>
                  <p className="truncate font-mono text-[11px] text-muted">{item.id}</p>
                </div>
                <button
                  type="button"
                  onClick={() => void restoreQuarantined(item.id)}
                  disabled={busyId === item.id}
                  className="shrink-0 px-2 py-1 text-accent hover:bg-accent-soft disabled:opacity-40"
                >
                  Restore
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
