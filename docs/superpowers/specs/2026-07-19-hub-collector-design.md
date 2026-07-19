# Hub + Collector Architecture

**Date:** 2026-07-19  
**Status:** Approved for implementation (v0.9.0)

## Goal

Memloom is **one Hub, many Collectors**.

- **Hub** (`memloom serve`): authoritative store, ingest pipeline, embed, search, MCP, admin dashboard.
- **Collector** (`memloom collector`): installed where data lives, bound to a Hub via endpoint + ingest key, extracts records and `POST /ingest`.

SSH pull and Runner direct-write remain **Legacy**. In-process Agent exporters are **Future**.

## Roles

| Role | Responsibility | Auth |
|------|----------------|------|
| Hub | Ingest → privacy → dedup → store → embed; read APIs; ops | Split keys (below) |
| Collector | Bind Hub; run source adapters; watermark; batch POST | Ingest key only |
| Source adapter | Local FS / DB / Mongo → `MemoryRecord[]` | None |

AnythingLLM push (or other outbound vector mirrors) is a **Hub-side** optional export — not part of Collector.

## Collector config contract

```yaml
# Prefer `hub`; `endpoint` accepted as alias (sync compat)
hub: http://192.168.5.101:8789/ingest
api_key: memloom_ingest_xxxxx   # or env MEMLOOM_INGEST_KEY
batch_size: 500
skip_embed: false
state_dir: ~/.memloom-collector
interval: 300                   # seconds when --loop

sources:
  - type: opencode
    db: ~/.local/share/opencode/opencode.db
  - type: librechat
    mongo_uri: mongodb://librechat-mongodb:27017/
    database: LibreChat
  - type: openclaw_session
    session_dir: /path/to/sessions
```

CLI:

```bash
memloom collector run CONFIG.yaml --once
memloom collector run CONFIG.yaml --loop --interval 300
memloom sync …   # deprecated alias
```

## Hub auth (three keys)

| Env | Protects |
|-----|----------|
| `MEMLOOM_INGEST_KEY` | `POST /ingest` only |
| `MEMLOOM_READ_KEY` | `/api/search`, `/mcp`, and other read HTTP APIs |
| `MEMLOOM_ADMIN_KEY` | `/api/admin/*` |

Fallback for 0.8 compat:

- READ unset → `MEMLOOM_INGEST_KEY` (log warning)
- ADMIN unset → `MEMLOOM_INGEST_KEY` (existing behavior)

## Deployment (machine-centric)

| Data location | Collector runs on |
|---------------|-------------------|
| 101 LibreChat / openclaw-coder | 101 (sidecar or host) |
| Mac Studio agents | Mac |
| hz agents | hz |
| Hub SSH into remote | **Not supported** (Legacy) |

Collectors depend on local filesystem or locally reachable services. They do **not** share Hub volumes.

## Legacy

- `memloom collect` + `Runner` direct-write to `RawStore` (tests / emergency local-bypass)
- `transport: ssh` in Hub YAML — implemented, undocumented as recommended path
- Dual adapter trees (`memloom/collectors/` pull vs `memloom/collector/` push) until a later cleanup release

## Future

- In-process `MemloomExporter(hub, key)` for openclaw / opencode plugins
- Multiple ingest keys scoped by `source` / host
- Remove Runner local-bypass from production docs entirely

## Non-goals (this release)

- SSH productization
- Hub-centralized remote scheduling
- Deleting `AgentAdapter` / Runner
