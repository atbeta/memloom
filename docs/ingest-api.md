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

- **Auth is required** for `/ingest`. The server refuses unauthenticated
  requests with 401. There is no fallback or "open" mode.
- **Bind address**: default `0.0.0.0` (listens on all interfaces). Use
  `--host 127.0.0.1` for local-only. Or keep `0.0.0.0` and put a reverse
  proxy with TLS in front.
- **Key rotation**: set a new `MEMLOOM_INGEST_KEY` env var and restart
  the server. Old key immediately stops working.
- **Audit**: check the run history with `mp status` and look for recent
  `run_id` entries. Each ingest call writes one.

## Why push instead of pull?

We considered the alternative (memloom SSHing into Mac Studio to read
SQLite). Push wins for several reasons:

| | Pull (SSH+SQLite) | Push (HTTP) |
|---|---|---|
| Mac Studio must run SSH | Yes | No |
| memloom on Mac Studio | No | No |
| Cron | On coder | On Mac Studio |
| Firewalled network | Needs inbound | Just outbound |
| Auth | SSH key | Bearer token (rotatable) |
| Adds new sources | New adapter per source | Same `POST /ingest` |

Use pull (adapters like `OpenClawSessionAdapter`, `LibreChatAdapter`)
when the host is already networked and you want zero-touch collection.
Use push (this API) when the host is closed off or the data producer
wants full control over what gets sent.
