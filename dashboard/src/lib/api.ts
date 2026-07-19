const KEY_STORAGE = 'memloom_admin_key'

export function getKey(): string | null {
  return sessionStorage.getItem(KEY_STORAGE)
}

export function setKey(key: string): void {
  sessionStorage.setItem(KEY_STORAGE, key)
}

export function clearKey(): void {
  sessionStorage.removeItem(KEY_STORAGE)
}

export class ApiError extends Error {
  status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

function authHeaders(): HeadersInit {
  const key = getKey()
  if (!key) {
    throw new ApiError(401, 'API key required')
  }
  return {
    Authorization: `Bearer ${key}`,
    Accept: 'application/json',
  }
}

async function handle<T>(res: Response): Promise<T> {
  if (res.status === 401) {
    clearKey()
    throw new ApiError(401, 'Unauthorized')
  }
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      detail = body.detail ? String(body.detail) : JSON.stringify(body)
    } catch {
      detail = await res.text()
    }
    throw new ApiError(res.status, detail || res.statusText)
  }
  if (res.status === 204) {
    return undefined as T
  }
  return res.json() as Promise<T>
}

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const url = new URL(path, window.location.origin)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') {
        url.searchParams.set(k, String(v))
      }
    }
  }
  const res = await fetch(url.pathname + url.search, { headers: authHeaders() })
  return handle<T>(res)
}

export async function apiSend<T>(
  method: 'POST' | 'PATCH',
  path: string,
  body?: unknown,
): Promise<T> {
  const res = await fetch(path, {
    method,
    headers: {
      ...authHeaders(),
      'Content-Type': 'application/json',
    },
    body: body === undefined ? undefined : JSON.stringify(body),
  })
  return handle<T>(res)
}

export type Overview = {
  total: number
  by_source: Record<string, number>
  vectors: number
  runs: RunRow[]
  data_root: string
  embed_enabled: boolean
  agent_count: number
  host_count: number
}

export type RunRow = {
  run_id: string
  source: string
  host: string
  started_at: number
  finished_at: number | null
  discovered: number
  new_records: number
  duplicates: number
  filtered: number
  errors: string[]
  duration_ms?: number
}

export type SearchHit = {
  id: string
  source: string
  source_key: string
  role: string
  content: string
  score: number
  agent: string
  project: string | null
  captured_at: number | null
  path: string
}

export type RecordDetail = {
  id: string
  source: string
  source_key: string
  agent: string
  project: string | null
  role: string
  captured_at: number | null
  occurred_at: number | null
  json_path: string
  md_path: string
  record: Record<string, unknown>
  markdown: string
}

export type Settings = {
  path: string | null
  writable: boolean
  pipeline: {
    data_root: string
    log_level: string
    chunk_size: number
  }
  privacy: {
    enabled: boolean
    strip_patterns: string[]
    redact_replacement: string
  }
  denoise: { enabled: boolean }
  embed: {
    enabled: boolean
    base_url: string
    api_key_set: boolean
    api_key: string
    model: string
    dimension: number
    batch_size: number
    timeout: number
    max_retries: number
    max_chars: number
    max_length: number
  }
  hosts: Array<{
    name: string
    transport: string
    ssh_host?: string | null
    ssh_user?: string | null
    ssh_port?: number
    ssh_key_file?: string | null
  }>
  agents: Array<{
    type: string
    host: string
    enabled: boolean
    options: Record<string, unknown>
  }>
  anythingllm: {
    enabled: boolean
    base_url: string
    api_key_set: boolean
    api_key: string
    workspace_slug: string
    auto_embed: boolean
  }
  warnings?: string[]
}

export type QuarantineItem = {
  id: string
  source: string
  source_key?: string
  role?: string
  captured_at?: number
  path?: string
}
