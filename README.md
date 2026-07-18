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

## v0.1 scope

* **Agents**: OpenClaw, Claude Code, Codex CLI, Generic JSONL fallback
* **Hosts**: local + SSH (e.g. Mac Studio collecting from a home server)
* **Pipeline**: collect → privacy-filter → tag → dedup → persist
* **Retrieval**: CLI `mp search` over SQLite FTS5
* **Not in v0.1** (designed for, not implemented): SaaS adapters (GitHub/Feishu/Notion),
  vector store integration, MCP server, browser extensions

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

# 3. Collect once
mp collect

# 4. Search
mp search "memory pipeline"
mp search --source openclaw "Beta preferences"

# 5. Inspect a record
mp inspect rec_abc123...

# 6. Status
mp status
```

## Layout

```
data/                          # data_root from config
  raw/<source>/<key>.json      # canonical record
  raw/<source>/<key>.md        # human-readable mirror
  index.sqlite                 # FTS5 over all records
  runs.sqlite                  # collector run history
  watermarks.json              # incremental cursors
```

## Cron

`scripts/install-cron.sh` registers `mp collect` every 5 minutes in the user's crontab.
Idempotent — re-running picks up only what changed.

## Architecture

```
Agents ──► Collectors ──► Pipeline ──► RawStore
                                  │
                                  └──► (future) Vector index
                                  └──► (future) MCP server
```

* **Collectors**: one per agent type. They know the agent's on-disk format and
  yield `MemoryRecord`s. They don't know about persistence.
* **Transport**: pluggable. `LocalTransport` for local files, `SSHTransport`
  (Fabric) for remote. Collectors ask the transport to read/list — they don't
  care which one.
* **Pipeline**: pure transforms on records — privacy filter, tag inference,
  deduper. Composable.
* **RawStore**: append-only-ish writes keyed by content hash. Three artifacts
  per record (json + md + sqlite row). FTS5 index for retrieval.

## Adding a new agent

1. Subclass `AgentAdapter` in `memory_pipeline/collectors/your_agent.py`.
2. Implement `discover()` (return list of `Source`) and `pull()` (yield
   `(MemoryRecord, Watermark)` pairs).
3. Register in `memory_pipeline/collectors/__init__.py:_REGISTRY`.
4. Add a config block under `agents:`.

That's it — pipeline + transport + store need zero changes.

## Future (architecture already supports it)

* v0.2: GitHub / Feishu / Notion / Email / browser extensions → drop in
  collectors under `collectors/saas/`.
* v0.2: AnythingLLM integration via push to its Custom Embedding API.
* v0.2: MCP server exposing `search_records` + `get_record` for OpenClaw.
* v0.3: Graph layer (relationships between records, projects, agents).

## License

MIT