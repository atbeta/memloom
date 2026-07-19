# Memloom Dashboard (Phase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship a read-only admin SPA + `/api/admin` APIs for overview, runs, search, and record detail — replacing AnythingLLM browse/ops without chat.

**Architecture:** New `memloom/admin/` FastAPI router mounted in `create_app`; React+Vite SPA in `dashboard/` proxied in dev and statically served in prod. Reuse `RawStore` / embedder search paths.

**Tech Stack:** FastAPI, pytest, React 19, Vite 6, TypeScript, Tailwind 4, react-router 7

## Global Constraints

- No chat UI; no MCP call-log fantasy; no Phase 2 settings/actions in this plan
- Admin routes require Bearer (`MEMLOOM_ADMIN_KEY` or fallback `MEMLOOM_INGEST_KEY`)
- Do not break existing `/ingest`, `/health`, `/stats`, `/api/search`, `/mcp`
- Prefer Chinese UI copy only if existing product strings are Chinese; otherwise English matching CLI
- No unsolicited git commits unless the user asks

## File structure

| Path | Responsibility |
|---|---|
| `memloom/store/raw.py` | Add `get_record(id)` |
| `memloom/admin/__init__.py` | Package export |
| `memloom/admin/auth.py` | Bearer dependency for admin |
| `memloom/admin/router.py` | `/api/admin/*` endpoints |
| `memloom/ingest_server.py` | Mount admin router + SPA static |
| `tests/test_admin_api.py` | Admin API tests |
| `tests/test_store.py` | `get_record` tests (extend) |
| `dashboard/*` | Vite React SPA (Phase 1 pages) |

---

### Task 1: `RawStore.get_record`

**Files:**
- Modify: `memloom/store/raw.py`
- Test: `tests/test_store.py`

**Interfaces:**
- Produces: `RawStore.get_record(self, record_id: str) -> dict | None`
  - On hit: `{id, source, source_key, agent, project, role, captured_at, occurred_at, json_path, md_path, record: dict, markdown: str}`
  - `record` = parsed JSON file; `markdown` = md file text (empty string if missing)
  - On miss: `None`

- [ ] **Step 1: Write the failing test**

Add to `tests/test_store.py` (follow existing fixture patterns):

```python
def test_get_record_roundtrip(tmp_path):
    from memloom.store import RawStore
    from memloom.records import MemoryRecord

    store = RawStore(tmp_path)
    rec = MemoryRecord(
        source="test",
        source_key="k1",
        content="hello admin",
        role="note",
    )
    store.upsert(rec)
    got = store.get_record(rec.id)
    assert got is not None
    assert got["id"] == rec.id
    assert got["record"]["content"] == "hello admin"
    assert "hello admin" in got["markdown"]
    assert store.get_record("rec_nonexistent") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_store.py::test_get_record_roundtrip -v`  
Expected: FAIL (`get_record` missing)

- [ ] **Step 3: Implement `get_record`**

In `RawStore`, after `has()`:

```python
def get_record(self, record_id: str) -> dict | None:
    with self._connect(self.index_path) as c:
        row = c.execute(
            """SELECT id, source, source_key, agent, project, role,
                      captured_at, occurred_at, json_path, md_path
               FROM records WHERE id=?""",
            (record_id,),
        ).fetchone()
    if not row:
        return None
    json_path = Path(row[8])
    md_path = Path(row[9])
    record_data: dict = {}
    markdown = ""
    if json_path.is_file():
        record_data = json.loads(json_path.read_text(encoding="utf-8"))
    if md_path.is_file():
        markdown = md_path.read_text(encoding="utf-8")
    return {
        "id": row[0], "source": row[1], "source_key": row[2],
        "agent": row[3] or "", "project": row[4], "role": row[5] or "",
        "captured_at": row[6], "occurred_at": row[7],
        "json_path": str(json_path), "md_path": str(md_path),
        "record": record_data, "markdown": markdown,
    }
```

Note: confirm `records` table has `source_key` column (it does in schema).

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_store.py::test_get_record_roundtrip -v`  
Expected: PASS

---

### Task 2: Admin auth + router (overview / runs / search / record)

**Files:**
- Create: `memloom/admin/__init__.py`
- Create: `memloom/admin/auth.py`
- Create: `memloom/admin/router.py`
- Modify: `memloom/ingest_server.py` (mount router)
- Test: `tests/test_admin_api.py`

**Interfaces:**
- Consumes: `RawStore.stats`, `recent_runs`, `search`, `hybrid_search`, `get_record`; optional `Embedder` from app state
- Produces: `APIRouter` prefix `/api/admin` via `build_admin_router(store, config, embedder)`

- [ ] **Step 1: Write failing API tests**

```python
# tests/test_admin_api.py — use same cfg_and_key pattern as test_ingest_server.py

def test_admin_requires_auth(client):
    c, _ = client
    assert c.get("/api/admin/overview").status_code == 401

def test_admin_overview_ok(client):
    c, key = client
    r = c.get("/api/admin/overview", headers={"Authorization": f"Bearer {key}"})
    assert r.status_code == 200
    body = r.json()
    assert "total" in body
    assert "by_source" in body
    assert "vectors" in body
    assert "runs" in body
    assert "data_root" in body

def test_admin_search_and_get(client, cfg_and_key):
    c, key = client
    cfg, _ = cfg_and_key
    from memloom.store import RawStore
    from memloom.records import MemoryRecord
    store = RawStore(cfg.pipeline.data_root)
    rec = MemoryRecord(source="opencode", source_key="s1", content="alpha beta gamma", role="note")
    store.upsert(rec)
    hdr = {"Authorization": f"Bearer {key}"}
    s = c.get("/api/admin/search", params={"q": "alpha", "hybrid": "false"}, headers=hdr)
    assert s.status_code == 200
    assert any(x["id"] == rec.id for x in s.json())
    g = c.get(f"/api/admin/records/{rec.id}", headers=hdr)
    assert g.status_code == 200
    assert g.json()["record"]["content"] == "alpha beta gamma"
    assert c.get("/api/admin/records/rec_nope", headers=hdr).status_code == 404
```

Wire `create_app` so these routes exist (tests fail until Task 2 impl).

- [ ] **Step 2: Implement auth helper**

`memloom/admin/auth.py`: verify Bearer against `os.environ.get("MEMLOOM_ADMIN_KEY") or os.environ.get("MEMLOOM_INGEST_KEY")` with `secrets.compare_digest`. Fail closed if neither set.

- [ ] **Step 3: Implement router**

`build_admin_router(store, config, embedder=None) -> APIRouter`:

- `GET /overview` → stats + runs(20) + `{data_root, embed_enabled, agent_count, host_count}`
- `GET /runs?limit=50`
- `GET /search?q=&source=&limit=20&hybrid=true` — same logic as existing `/api/search`
- `GET /records/{record_id}` — `get_record` or 404

- [ ] **Step 4: Mount in `create_app`**

```python
from .admin.router import build_admin_router
app.include_router(build_admin_router(store, config, embedder))
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_admin_api.py tests/test_store.py::test_get_record_roundtrip -v`  
Expected: all PASS  
Also: `uv run pytest tests/test_ingest_server.py -v` must still PASS

---

### Task 3: Scaffold dashboard SPA + proxy

**Files:**
- Create: `dashboard/` Vite React TS app (package.json, vite.config with proxy, tailwind)
- Pages: Overview, Explorer, Pipeline
- Shared: auth key prompt, API client

**Interfaces:**
- Consumes: `/api/admin/*` with Bearer from sessionStorage key `memloom_admin_key`
- Vite proxy: `/api` → `http://127.0.0.1:8789`

- [ ] **Step 1: Scaffold**

```bash
cd /Users/beta/Projects/memloom
npm create vite@latest dashboard -- --template react-ts
cd dashboard && npm i && npm i react-router-dom && npm i -D tailwindcss @tailwindcss/vite
```

Configure Tailwind 4 via `@tailwindcss/vite`. Add proxy in `vite.config.ts`.

- [ ] **Step 2: API client + auth gate**

`dashboard/src/lib/api.ts`: `getKey()`, `setKey()`, `apiGet(path, params)` throwing on 401.

- [ ] **Step 3: Pages**

- `Overview`: fetch `/api/admin/overview` — totals, by_source table, recent runs snippet
- `Explorer`: search input → results list → select → `/api/admin/records/{id}` show markdown/json in `<pre>`
- `Pipeline`: `/api/admin/runs` table
- Shell nav between three routes; key entry screen when missing/401

- [ ] **Step 4: Manual smoke**

Terminal A: `MEMLOOM_INGEST_KEY=dev uv run memloom serve -c <config> --host 127.0.0.1`  
Terminal B: `cd dashboard && npm run dev`  
Open UI, paste key, verify search + overview.

---

### Task 4: Serve SPA from FastAPI (prod)

**Files:**
- Modify: `memloom/ingest_server.py` or `memloom/admin/static.py`
- Modify: `dashboard/vite.config.ts` (`base: '/'`, `outDir` optional)
- Docs: short section in `README.md` or `docs/dashboard.md`

- [ ] **Step 1: Build output path**

Build to `memloom/admin/static/` (gitignored contents except `.gitkeep`) OR document `dashboard/dist` mount path.

Recommended: `dashboard/vite.config.ts`:

```ts
build: { outDir: '../memloom/admin/static', emptyOutDir: true }
```

Add `memloom/admin/static/.gitkeep` and gitignore `memloom/admin/static/**` except gitkeep.

- [ ] **Step 2: Mount StaticFiles + SPA fallback**

After API routes, if static dir has `index.html`, mount assets and catch-all to `index.html` for client routes. Do not shadow `/api`, `/ingest`, `/health`, `/mcp`.

- [ ] **Step 3: Document**

```bash
cd dashboard && npm run build
MEMLOOM_INGEST_KEY=... uv run memloom serve -c ./config/memloom.yaml
# open http://127.0.0.1:8789/
```

---

### Task 5: Phase 1 verification checklist

- [ ] `uv run pytest` green
- [ ] README mentions dashboard briefly
- [ ] Design non-goals still respected (no chat, no settings write, no fake MCP metrics)

---

## Phase 2 (out of this plan)

Settings forms + `PATCH` config; `POST` collect/embed/quarantine actions. Separate plan after Phase 1 ships.
