# Memloom Dashboard Design

**Date:** 2026-07-19  
**Status:** Approved (approach 1; Phase 1 first)

## Goal

Replace AnythingLLM’s **knowledge browse + ops** surface with a Memloom-native Web UI.  
No in-app chat. CLI remains the source of truth for advanced workflows.

## Non-goals

- RAG chat UI
- Vim-mode Monaco YAML editor as primary settings UX
- MCP connection/call-log dashboards (backend has no such telemetry)
- GraphQL
- Public / Cloudflare-grade auth hardening in Phase 1

## Product scope

| Capability | Phase 1 (read-only) | Phase 2 (target C) |
|---|---|---|
| Overview: totals, by-source, vector count | yes | yes |
| Recent collector runs | yes | yes |
| Search (FTS5 / hybrid) + record detail | yes | yes |
| Settings forms (agents/hosts/embed/privacy) | — | yes |
| Trigger collect / embed / quarantine | — | yes |
| Advanced config still via YAML file | yes (external) | yes (external) |

If Phase 2 proves too heavy, ship Phase 1 alone (fallback A).

## Architecture

```
Browser (React SPA)
    │  Bearer (MEMLOOM_INGEST_KEY or optional MEMLOOM_ADMIN_KEY)
    ▼
memloom serve (FastAPI, one process)
    ├── /ingest, /health, /stats, /api/search, /mcp   (existing)
    ├── /api/admin/*                                  (new admin router)
    └── /                                             (SPA static, after build)
         │
         ▼
    RawStore / Runner / config (reuse Python modules)
```

**Principles**

1. Admin APIs live in `memloom/admin/` — not stuffed into ingest handlers.
2. Reuse store/runner/config; do not invent parallel data models.
3. LAN/localhost trusted network; optional separate admin key, default shared ingest key.
4. Gemini’s Trae scaffold / PRD are discarded; rebuild UI against real APIs.

## Admin API (Phase 1)

All under `/api/admin`, require Bearer auth.

| Method | Path | Behavior |
|---|---|---|
| GET | `/api/admin/overview` | `store.stats()` + `recent_runs(limit)` + config summary (data_root, embed.enabled, agent count) |
| GET | `/api/admin/runs` | Recent runs (`limit` query, default 50) |
| GET | `/api/admin/search` | Wrap existing search/hybrid logic (`q`, `source`, `limit`, `hybrid`) |
| GET | `/api/admin/records/{id}` | Resolve id via SQLite → return JSON + markdown text |

Phase 2 (later): `GET/PATCH /api/admin/settings`, `POST /api/admin/actions/collect|embed`, quarantine endpoints.

## Store gap

`RawStore` has no `get(id)` today; CLI `inspect` uses filesystem `rglob`.  
Add `RawStore.get_record(record_id) -> dict | None` reading `json_path` / `md_path` from the index.

## Frontend (Phase 1)

- **Stack:** React 19 + Vite + TypeScript + Tailwind 4 + react-router
- **Pages:** `/` Overview · `/explorer` Search+detail · `/pipeline` Runs table
- **UI:** Desktop-first, high information density, restrained motion; not “console green hacker” theme
- **Dev:** Vite proxy `/api` → `memloom serve`
- **Prod:** `npm run build` → assets served by FastAPI from `memloom/admin/static/` (or `dashboard/dist` mounted)

## Settings (Phase 2 only)

Form fields for common knobs: pipeline.data_root, privacy.enabled/patterns, embed.*, hosts[], agents[] (type/host/enabled).  
Secrets (api_key) write-only / masked on read. Full YAML remains the escape hatch on disk.

## Auth

- Require `Authorization: Bearer <key>` on all `/api/admin/*`
- Accept `MEMLOOM_ADMIN_KEY` if set, else `MEMLOOM_INGEST_KEY`
- SPA stores key in `sessionStorage` (not localStorage); prompt on first visit
- `/health` stays public for probes

## Testing

- Pytest for admin router (auth, overview, search, get record 404)
- Store unit test for `get_record`
- Manual smoke: serve + Vite proxy

## Open decisions deferred to Phase 2

- Whether collect runs sync in-request or background job
- Config write atomicity / backup of YAML before save
- Deprecating AnythingLLM push UI (CLI can remain)
