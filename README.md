# memory-pipeline

Unified agent memory collection + local knowledge base.

Collects memory from multiple AI agents (OpenClaw, Claude Code, Codex, etc.) on
local or SSH-reachable hosts, stores them as a raw-preserving data lake (JSON +
markdown + SQLite FTS5), and exposes full-text search via a CLI.

## Why

Every agent has its own memory. None of them talk to each other. This tool is
the bottom layer of a stack that lets you grep/search/retrieve across all of
them from one place.

The v0.1 design keeps everything raw — original files are copied (or referenced)
to disk in their original form, with derived layers (facts, vector indices,
graph relations) added on top later. You can always go back to the source.

## v0.9 scope (Hub + Collector)

* **Hub** (`memloom serve`): ingest → store → embed → search / MCP / dashboard
* **Collector** (`memloom collector`): runs where data lives, pushes via ingest key
* **Sources**: OpenClaw, LibreChat, OpenCode, Codex, Hermes, Kilo, Qoder, …
* **Legacy**: `memloom collect` (local Runner) and SSH transport — not recommended
* See [docs/collector.md](docs/collector.md) and [hub-collector design](docs/superpowers/specs/2026-07-19-hub-collector-design.md)

## Install

```bash
uv sync
# or: pip install -e .
```

## Quick start

```bash
# 1. Drop a starter config
mp init-config ./config/memory-pipeline.yaml

# 2. Edit it: pick which agents, which hosts

# 3. Start Hub
export MEMLOOM_INGEST_KEY=...
export MEMLOOM_READ_KEY=...    # optional; falls back to ingest
export MEMLOOM_ADMIN_KEY=...   # optional; falls back to ingest
uv run memloom serve --config ./config/memloom.yaml --host 127.0.0.1

# 4. On each machine with data — run a collector
cp config/collector.yaml.example ~/.config/memloom/collector.yaml
# edit hub + sources
memloom collector run ~/.config/memloom/collector.yaml --once

# 5. Search / dashboard
mp search "memory pipeline"
# http://127.0.0.1:8789/  (see docs/dashboard.md)
```

## Layout

```
data/                          # Hub data_root
  raw/<source>/<key>.json
  raw/<source>/<key>.md
  index.sqlite
  runs.sqlite
```

## Collector config

```yaml
# see config/collector.yaml.example and docs/collector.md
hub: http://192.168.5.101:8789/ingest
sources:
  - type: opencode
    db: ~/.local/share/opencode/opencode.db
```

## Architecture

```
Mac/hz/101 Collectors ──POST /ingest──► Hub (store + embed + MCP + dashboard)
```

* **Hub**: authoritative pipeline and retrieval.
* **Collector**: Hub-bound; filesystem/DB adapters; watermarks; batch ingest.
* **Legacy**: `memloom collect` + SSH pull — prefer a collector on the data host.

## Adding a new agent

1. Subclass `AgentAdapter` in `memloom/collectors/your_agent.py`.
2. Implement `discover()` (return list of `Source`) and `pull()` (yield
   `(MemoryRecord, Watermark)` pairs).
3. Register in `memloom/collectors/__init__.py:_REGISTRY`.
4. Add a config block under `agents:`.

That's it — pipeline + transport + store need zero changes.

## Commit message format

We follow [Conventional Commits](https://www.conventionalcommits.org/) (English,
unless otherwise stated). Every commit message **must** match this format:

```
<type>(<scope>): <subject>     ←  ≤72 chars, imperative, no period

[optional body]                 ←  wrap at ~72 chars, explain WHAT and WHY

[optional footer]               ←  BREAKING CHANGE: or Refs: #123
```

**Types**: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`,
`build`, `ci`, `perf`, `revert`. **Breaking changes** use a `!` after the
type/scope (`feat(api)!: drop v1 endpoint`) or a `BREAKING CHANGE:` footer.

**Scopes** (project-specific): `collectors`, `store`, `pipeline`,
`transport`, `vector`, `mcp`, `cli`, `config`, `docs`, `deps`, `ci`.

The repo ships with a `.gitmessage` template and a `commit-msg` git hook
that enforces the format. To enable the hook after cloning:

```bash
./scripts/install-hooks.sh
git config commit.template .gitmessage
```

Examples:

```
feat(collectors): add OpenCode adapter
fix(privacy): strip ghp_ tokens from raw_meta
docs: add AnythingLLM integration guide
refactor(store)!: drop legacy v1 schema
chore(deps): bump pydantic to 2.13
```

## Future (architecture already supports it)

* v0.2: GitHub / Feishu / Notion / Email / browser extensions → drop in
  collectors under `collectors/saas/`.
* v0.2: AnythingLLM integration via push to its Custom Embedding API.
* v0.2: MCP server exposing `search_records` + `get_record` for OpenClaw.
* v0.3: Graph layer (relationships between records, projects, agents).

## License

MIT