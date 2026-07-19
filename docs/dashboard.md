# Memloom Dashboard (Phase 1)

Read-only web console for store overview, search, and collector runs.
Replaces AnythingLLM’s browse/ops surface — **no chat**.

## Dev

```bash
# Terminal A — API
export MEMLOOM_INGEST_KEY=dev_key_change_me
export MEMLOOM_ADMIN_KEY=dev_admin_key   # optional; falls back to ingest
uv run memloom serve --config ./config/memloom.yaml --host 127.0.0.1 --port 8789

# Terminal B — UI (proxies /api → :8789)
cd dashboard
npm install
npm run dev
# → http://127.0.0.1:5173  (paste the same key)
```

## Production (single process)

```bash
cd dashboard && npm run build
# writes to memloom/admin/static/

export MEMLOOM_INGEST_KEY=...
uv run memloom serve --config ./config/memloom.yaml --host 127.0.0.1 --port 8789
# → http://127.0.0.1:8789/
```

Keys:

| Env | Used for |
|-----|----------|
| `MEMLOOM_INGEST_KEY` | Collectors → `POST /ingest` |
| `MEMLOOM_READ_KEY` | MCP / HTTP search (fallback: ingest) |
| `MEMLOOM_ADMIN_KEY` | Dashboard admin API (fallback: ingest) |

Paste the **admin** key (or ingest if admin unset) into the dashboard login.

## Pages

| Route | Purpose |
|---|---|
| `/` | Totals, by-source, recent runs, embed backfill |
| `/explorer` | FTS5 / hybrid search + raw JSON/Markdown + quarantine |
| `/pipeline` | Collector run history + **Run collect** |
| `/settings` | Common config form (YAML still escape hatch) |

## Notes

- Start serve with `--config` so Settings can write (creates `.yaml.bak` on save).
- Changing `data_root` requires restarting the server.
- Secrets (`embed.api_key`) are never returned in cleartext; leave blank to keep.
