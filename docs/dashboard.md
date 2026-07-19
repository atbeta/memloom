# Memloom Dashboard (Phase 1)

Read-only web console for store overview, search, and collector runs.
Replaces AnythingLLM’s browse/ops surface — **no chat**.

## Dev

```bash
# Terminal A — API
export MEMLOOM_INGEST_KEY=dev_key_change_me
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

Optional: set `MEMLOOM_ADMIN_KEY` to use a key different from ingest.

## Pages

| Route | Purpose |
|---|---|
| `/` | Totals, by-source, recent runs |
| `/explorer` | FTS5 / hybrid search + raw JSON/Markdown |
| `/pipeline` | Collector run history |

## Phase 2 (not yet)

Settings forms, trigger collect/embed/quarantine — see
`docs/superpowers/specs/2026-07-19-memloom-dashboard-design.md`.
