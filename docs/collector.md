# Memloom Collector

A **Collector** runs on the machine that has agent data, binds to a **Hub**
(`memloom serve`), and pushes records via `POST /ingest` using an ingest key.

```
Mac / hz / 101  ──collector──►  Hub (101 :8789)
```

Do **not** SSH from the Hub into remotes. Install a collector where the files live.

## Install

```bash
pip install memloom
# or: uv tool install memloom
export MEMLOOM_INGEST_KEY=memloom_ingest_xxxxx
```

Copy an example:

- [`config/collector.yaml.example`](../config/collector.yaml.example)
- [`config/collector.mac.example.yaml`](../config/collector.mac.example.yaml)
- [`config/collector.hz.example.yaml`](../config/collector.hz.example.yaml)

## Run

```bash
# One incremental pass
memloom collector run ~/.config/memloom/collector.yaml --once

# Full re-extract (ignore watermarks)
memloom collector run ~/.config/memloom/collector.yaml --full

# Loop (production sidecar)
memloom collector run ~/.config/memloom/collector.yaml --loop --interval 300

# Dry-run
memloom collector run ./collector.yaml --once --dry-run
```

`memloom sync` remains as a deprecated alias.

## Config fields

| Field | Meaning |
|-------|---------|
| `hub` | Hub ingest URL (`http://host:8789` or `.../ingest`) |
| `endpoint` | Alias for `hub` (legacy sync configs) |
| `api_key` | Ingest key (or env `MEMLOOM_INGEST_KEY`) |
| `sources[]` | Local adapters (`opencode`, `librechat`, `openclaw`, …) |
| `state_dir` | Watermark file directory |
| `interval` | Default `--loop` sleep seconds |

## Scheduling

**cron (Linux):**

```cron
*/5 * * * * MEMLOOM_INGEST_KEY=... /usr/local/bin/memloom collector run /etc/memloom/collector.yaml --once
```

**systemd timer:** oneshot service + `OnUnitActiveSec=5min`.

**launchd (macOS):** `StartInterval` 300 calling the same command.

**Docker (101):** `memloom-collect` sidecar with `--loop` (see lab compose).

## Auth

Collectors only need `MEMLOOM_INGEST_KEY`. Hub read/MCP should use `MEMLOOM_READ_KEY`;
dashboard uses `MEMLOOM_ADMIN_KEY`. See [hub-collector design](superpowers/specs/2026-07-19-hub-collector-design.md).

## Legacy

- `memloom collect` (Runner direct-write) — tests / emergency local-bypass only
- SSH `transport` on Hub YAML — not recommended
