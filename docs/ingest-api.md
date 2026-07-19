# memloom ingest API

External tools push records into memloom via HTTP. This is the inverse
of the collector pattern — instead of memloom SSHing into your machine
to pull data, you POST it.

## Server

```bash
# Generate a fresh API key (printed once on first run if MEMLOOM_INGEST_KEY not set)
export MEMLOOM_INGEST_KEY=memloom_ingest_<your-key>
uv run memloom serve --config ./memloom.yaml --port 8765
# → "memloom-ingest server starting on http://0.0.0.0:8765"
```

For long-running deployment, run under systemd / launchd / docker. The
server reuses the same store and embedder as the local `mp collect`.

## Endpoints

### `POST /ingest` (Bearer auth)

```http
POST /ingest HTTP/1.1
Host: 192.168.5.101:8765
Authorization: Bearer memloom_ingest_xxxxx
Content-Type: application/json

{
  "records": [
    {
      "source": "opencode",
      "source_key": "session-abc/turn-1",
      "content": "How do I add a vector index to my db?",
      "role": "conversation_turn",
      "agent": "opencode:claude-sonnet-4",
      "project": "my-project",
      "occurred_at": 1752840000000,
      "raw_meta": {
        "model": "claude-sonnet-4-20250514",
        "tokens_in": 150,
        "tokens_out": 320
      }
    }
  ],
  "skip_embed": false
}
```

Field reference for each record:

| Field | Required | Notes |
|---|---|---|
| `source` | yes | e.g. `"opencode"`, `"obsidian"`, `"zotero"` |
| `source_key` | yes | unique within `source` (used for dedup) |
| `content` | yes | the text to embed + search |
| `role` | no | default `"note"` |
| `agent` | no | e.g. `"opencode:claude-sonnet"` |
| `project` | no | e.g. `"my-app"` (used for `project:` tag) |
| `occurred_at` | no | ms epoch |
| `visibility` | no | default `"personal"` |
| `raw_meta` | no | free-form dict, kept as-is |

Required-only minimum: `{source, source_key, content}`.

Response:

```json
{"accepted": 10, "skipped": 2, "errors": []}
```

Errors don't fail the whole request — they show up in the `errors` list
with index references. Server also applies privacy filtering, dedup on
`source+source_key`, and embedding (unless `skip_embed: true`).

### `GET /health` (no auth)

```json
{"status": "ok", "records": 1011, "vectors": 1011}
```

### `GET /stats` (no auth)

Same as `mp status`.

## Client (Python example)

```python
import requests, sqlite3, json

# 1. Read your local data
con = sqlite3.connect('/path/to/local.db')
rows = con.execute("SELECT id, content, ... FROM my_table").fetchall()

# 2. Convert to memloom records
records = []
for row in rows:
    records.append({
        "source": "my_source",
        "source_key": str(row.id),
        "content": row.content,
        "role": "note",
        "raw_meta": {"ts": row.created_at, ...},
    })

# 3. Push
r = requests.post(
    "http://192.168.5.101:8789/ingest",
    headers={"Authorization": f"Bearer {KEY}"},
    json={"records": records},
    timeout=300,
)
r.raise_for_status()
print(r.json())  # {"accepted": ..., "skipped": ..., "errors": []}
```

For bulk backfill, split into batches of ~500 records per request to
stay under the 10k-record per-call cap.

## Backfill workflow

For one-time historical imports:

```bash
# 1. Dump local data to JSON
python3 my_dump_script.py > /tmp/backfill.json

# 2. Push (split if huge)
mp ingest --url http://192.168.5.101:8789 --key "$KEY" /tmp/backfill.json

# 3. If you have lots of content, embed afterwards
mp embed --config /path/to/memloom.yaml
```

For incremental daily push, see the pattern in the OpenCode skill:
read the watermark from a state file, query only new records, push,
save the watermark.

## Security notes

- **`MEMLOOM_INGEST_KEY`**: required for `POST /ingest` only.
- **`MEMLOOM_READ_KEY`**: `/api/search` and `/mcp` (falls back to ingest key).
- **`MEMLOOM_ADMIN_KEY`**: `/api/admin/*` (falls back to ingest key).
- Unauthenticated ingest/read/admin → 401. No open mode.
- **Bind address**: default `0.0.0.0`. Use `--host 127.0.0.1` for local-only.
- **Key rotation**: change env and restart Hub.

## Recommended client: Collector

Prefer [`memloom collector`](collector.md) on every machine that has data.
It binds to this Hub with an ingest key and pushes incrementally.

```bash
memloom collector run ~/.config/memloom/collector.yaml --once
```

## Why push instead of SSH pull?

| | SSH pull (Legacy) | Collector push (recommended) |
|---|---|---|
| Remote must run SSH server | Yes | No |
| Install on data host | No | Yes (`memloom collector`) |
| Cron / launchd | On Hub | On each data host |
| Firewalled network | Needs inbound to data host | Outbound to Hub |
| Auth | SSH key | `MEMLOOM_INGEST_KEY` |

SSH transport remains in the codebase for emergency local-bypass / tests only.
