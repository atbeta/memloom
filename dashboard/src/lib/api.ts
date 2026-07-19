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

export async function apiGet<T>(
  path: string,
  params?: Record<string, string | number | boolean | undefined>,
): Promise<T> {
  const key = getKey()
  if (!key) {
    throw new ApiError(401, 'API key required')
  }

  const url = new URL(path, window.location.origin)
  if (params) {
    for (const [k, v] of Object.entries(params)) {
      if (v !== undefined && v !== '') {
        url.searchParams.set(k, String(v))
      }
    }
  }

  const res = await fetch(url.pathname + url.search, {
    headers: {
      Authorization: `Bearer ${key}`,
      Accept: 'application/json',
    },
  })

  if (res.status === 401) {
    clearKey()
    throw new ApiError(401, 'Unauthorized')
  }
  if (!res.ok) {
    const detail = await res.text()
    throw new ApiError(res.status, detail || res.statusText)
  }
  return res.json() as Promise<T>
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
