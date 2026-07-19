# Changelog

## [Unreleased]

### Added
- Admin dashboard Phase 1+2: Overview / Explorer / Pipeline / Settings SPA
- `/api/admin/overview|runs|search|records/{id}` (Bearer auth)
- `/api/admin/settings` GET/PATCH (common knobs; secrets masked)
- `/api/admin/actions/collect|embed` and quarantine list/add/restore
- `RawStore.get_record()` for id → JSON/Markdown lookup
- Shared `memloom.ops.embed_backfill` used by CLI + admin
- Optional `MEMLOOM_ADMIN_KEY` (falls back to `MEMLOOM_INGEST_KEY`)
- Docs: `docs/dashboard.md`, design/plan under `docs/superpowers/`

## [0.5.0] - 2026-07-19

### Added
- Denoiser pipeline step — strips JSON tool output wrapping for cleaner embeddings
-  config section (enabled by default)
- Applied in both collector runner and ingest server


## [0.4.3] - 2026-07-19

### Added
- `openclaw_chat` sync adapter — push OpenClaw native `.jsonl` session files

## [0.4.2] - 2026-07-19

### Added
- `openclaw_session` sync adapter — push OpenClaw trajectory sessions via HTTP ingest

## [0.4.0] - 2026-07-19

### Added
- `memloom sync run` — push local agent stores to a memloom ingest server
- Sync adapters: OpenCode (SQLite), Codex CLI (SQLite + rollout JSONL), Antigravity brain (markdown), Qoder (SQLite), Kilo Code (JSON files)
- `SyncConfig` — YAML-driven config for sync sources, endpoint, and API key
- `WatermarkStore` — file-backed incremental cursor, stored at `~/.memloom-sync/watermarks.json`
- `--dry-run`, `--source`, `--once` flags on `sync run`

### Fixed
- `memloom push --no-dedup` flag behavior documented

## [0.3.0] - 2026-07-15

### Added
- HTTP ingest server (`memloom serve`) with Bearer auth
- `POST /ingest` endpoint with privacy filter, tag inference, dedup
- `GET /health` and `GET /stats` endpoints
- `memloom ingest` command for file-based push
- LibreChat MongoDB adapter
- OpenClaw session trajectory adapter
- sqlite-vec vector index for hybrid search
- AnythingLLM push integration (`memloom push`)
- Embedding client (OpenAI-compatible `/v1/embeddings`)
- Quarantine system for soft-deleting low-value records

## [0.1.0] - 2026-06-01

### Added
- Initial release
- `memloom collect` — collect from agents via local or SSH transport
- Collectors: OpenClaw workspace, Claude Code, Codex CLI, Generic JSONL
- Privacy filter (secret/PII redaction)
- Content dedup and tag inference
- SQLite FTS5 search (`mp search`)
- `mp status`, `mp inspect`, `mp init-config`, `mp agents`
- Conventional Commits enforcement via git hook
