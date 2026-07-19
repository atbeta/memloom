import { useEffect, useState, type FormEvent, type ReactNode } from 'react'
import { ApiError, apiGet, apiSend, type Settings as SettingsData } from '@/lib/api'
import { StatusLine } from '@/components/StatusLine'

export default function Settings() {
  const [data, setData] = useState<SettingsData | null>(null)
  const [patternsText, setPatternsText] = useState('')
  const [agentsText, setAgentsText] = useState('')
  const [hostsText, setHostsText] = useState('')
  const [apiKeyDraft, setApiKeyDraft] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)

  async function load() {
    setLoading(true)
    setError(null)
    try {
      const body = await apiGet<SettingsData>('/api/admin/settings')
      setData(body)
      setPatternsText(body.privacy.strip_patterns.join('\n'))
      setAgentsText(JSON.stringify(body.agents, null, 2))
      setHostsText(JSON.stringify(body.hosts, null, 2))
      setApiKeyDraft('')
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

  async function onSave(e: FormEvent) {
    e.preventDefault()
    if (!data) return
    setSaving(true)
    setError(null)
    setNotice(null)
    try {
      let agents
      let hosts
      try {
        agents = JSON.parse(agentsText)
        hosts = JSON.parse(hostsText)
      } catch {
        throw new Error('hosts/agents JSON is invalid')
      }
      const embedPatch: Record<string, unknown> = {
        enabled: data.embed.enabled,
        base_url: data.embed.base_url,
        model: data.embed.model,
        dimension: data.embed.dimension,
        batch_size: data.embed.batch_size,
        timeout: data.embed.timeout,
      }
      if (apiKeyDraft.trim()) {
        embedPatch.api_key = apiKeyDraft.trim()
      }
      const body = await apiSend<SettingsData>('PATCH', '/api/admin/settings', {
        pipeline: data.pipeline,
        privacy: {
          enabled: data.privacy.enabled,
          redact_replacement: data.privacy.redact_replacement,
          strip_patterns: patternsText
            .split('\n')
            .map((s) => s.trim())
            .filter(Boolean),
        },
        denoise: data.denoise,
        embed: embedPatch,
        hosts,
        agents,
      })
      setData(body)
      setPatternsText(body.privacy.strip_patterns.join('\n'))
      setAgentsText(JSON.stringify(body.agents, null, 2))
      setHostsText(JSON.stringify(body.hosts, null, 2))
      setApiKeyDraft('')
      const warn = body.warnings?.length ? ` Warnings: ${body.warnings.join('; ')}` : ''
      setNotice(`Saved.${warn}`)
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        window.location.reload()
        return
      }
      setError(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  if (loading || !data) {
    return <StatusLine loading={loading} error={error} />
  }

  return (
    <form onSubmit={onSave} className="mx-auto max-w-3xl space-y-5">
      <div className="panel panel-pad space-y-2">
        <h2 className="section-title">Settings</h2>
        <p className="font-mono text-xs text-muted">
          {data.path ?? '(no config path — writes disabled)'}
          {data.writable ? '' : ' · read-only'}
        </p>
        <p className="text-sm leading-relaxed text-muted">
          Common knobs only. Advanced options stay in the YAML file on disk.
        </p>
      </div>

      <StatusLine error={error} />
      {notice ? <p className="font-mono text-sm text-accent">{notice}</p> : null}

      <section className="panel panel-pad space-y-4">
        <h3 className="text-sm font-medium">Pipeline</h3>
        <Field label="data_root">
          <input
            className="field"
            value={data.pipeline.data_root}
            onChange={(e) =>
              setData({ ...data, pipeline: { ...data.pipeline, data_root: e.target.value } })
            }
          />
        </Field>
        <Field label="log_level">
          <select
            className="field"
            value={data.pipeline.log_level}
            onChange={(e) =>
              setData({ ...data, pipeline: { ...data.pipeline, log_level: e.target.value } })
            }
          >
            {['DEBUG', 'INFO', 'WARNING', 'ERROR'].map((l) => (
              <option key={l} value={l}>
                {l}
              </option>
            ))}
          </select>
        </Field>
      </section>

      <section className="panel panel-pad space-y-4">
        <h3 className="text-sm font-medium">Privacy</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={data.privacy.enabled}
            onChange={(e) =>
              setData({ ...data, privacy: { ...data.privacy, enabled: e.target.checked } })
            }
          />
          enabled
        </label>
        <Field label="strip_patterns (one regex per line)">
          <textarea
            className="field min-h-28 font-mono text-xs"
            value={patternsText}
            onChange={(e) => setPatternsText(e.target.value)}
          />
        </Field>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={data.denoise.enabled}
            onChange={(e) => setData({ ...data, denoise: { enabled: e.target.checked } })}
          />
          denoise enabled
        </label>
      </section>

      <section className="panel panel-pad space-y-4">
        <h3 className="text-sm font-medium">Embed</h3>
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            checked={data.embed.enabled}
            onChange={(e) =>
              setData({ ...data, embed: { ...data.embed, enabled: e.target.checked } })
            }
          />
          enabled
        </label>
        <Field label="base_url">
          <input
            className="field"
            value={data.embed.base_url}
            onChange={(e) =>
              setData({ ...data, embed: { ...data.embed, base_url: e.target.value } })
            }
          />
        </Field>
        <Field label="model">
          <input
            className="field"
            value={data.embed.model}
            onChange={(e) =>
              setData({ ...data, embed: { ...data.embed, model: e.target.value } })
            }
          />
        </Field>
        <Field label={`api_key ${data.embed.api_key_set ? '(set — leave blank to keep)' : ''}`}>
          <input
            className="field font-mono"
            type="password"
            autoComplete="off"
            placeholder={data.embed.api_key_set ? '••••••••' : 'optional'}
            value={apiKeyDraft}
            onChange={(e) => setApiKeyDraft(e.target.value)}
          />
        </Field>
      </section>

      <section className="panel panel-pad space-y-3">
        <h3 className="text-sm font-medium">Hosts (JSON)</h3>
        <textarea
          className="field min-h-32 font-mono text-xs"
          value={hostsText}
          onChange={(e) => setHostsText(e.target.value)}
        />
      </section>

      <section className="panel panel-pad space-y-3">
        <h3 className="text-sm font-medium">Agents (JSON)</h3>
        <textarea
          className="field min-h-40 font-mono text-xs"
          value={agentsText}
          onChange={(e) => setAgentsText(e.target.value)}
        />
      </section>

      <button
        type="submit"
        disabled={!data.writable || saving}
        className="btn btn-primary px-5"
      >
        {saving ? 'Saving…' : 'Save settings'}
      </button>
    </form>
  )
}

function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <label className="block text-sm">
      <span className="text-muted">{label}</span>
      <div className="mt-1.5">{children}</div>
    </label>
  )
}
