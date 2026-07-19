"""HTTP ingest server for memloom.

External tools (OpenCode skill, manual scripts, etc) push records in via
HTTP instead of us pulling via SSH/DB. This is the inverse of the
collectors, and complements them.

API
---

``POST /ingest``:
    Auth:    ``Authorization: Bearer <MEMLOOM_INGEST_KEY>``
    Body:    ``{"records": [MemoryRecord, ...]}``
             Each record must have at minimum ``source`` and ``source_key``.
             Other fields follow the standard ``MemoryRecord`` schema.
    Response: ``{"accepted": int, "skipped": int, "errors": [str]}``

    The endpoint applies the same pipeline as local ``mp collect``:
    privacy filter → tag → dedup → upsert → (optional) embed.

``GET /health`` (no auth):
    Returns ``{"status": "ok", "records": int, "vectors": int}``.

``GET /stats`` (no auth):
    Returns the same output as ``mp status``.

Running
-------

.. code-block:: bash

    export MEMLOOM_INGEST_KEY=memloom_ingest_xxxxxxxx
    uv run memloom serve --port 8789 --config ./memloom.yaml

The server listens on ``0.0.0.0`` by default (so it can be reached from
other machines on the LAN). Set ``--host 127.0.0.1`` to bind locally only.
"""
from __future__ import annotations

import logging
import os
import secrets
from typing import Any

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, Field, ValidationError

from . import __version__
from .config import Config
from .pipeline import Deduper, Denoiser, PrivacyFilter, tag_record
from .records import MemoryRecord
from .store import RawStore


log = logging.getLogger(__name__)


# ---------- Request / response models ----------


class IngestRequest(BaseModel):
    records: list[dict[str, Any]] = Field(..., min_length=1, max_length=10_000)
    # Optional: tell server to skip embedding (for bulk backfills where you'll
    # run `mp embed` later)
    skip_embed: bool = False


class IngestResponse(BaseModel):
    accepted: int
    skipped: int
    errors: list[str] = Field(default_factory=list)


class HealthResponse(BaseModel):
    status: str
    records: int
    vectors: int


# ---------- Auth ----------


_bearer_scheme = HTTPBearer(auto_error=False)


def _verify_bearer(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> None:
    """FastAPI dependency: reject if the Bearer token doesn't match."""
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid Authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )
    expected = os.environ.get("MEMLOOM_INGEST_KEY")
    if not expected:
        # Server misconfig: no key set. Fail closed.
        log.error("MEMLOOM_INGEST_KEY is not set in server env — refusing all requests")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="server misconfiguration: no MEMLOOM_INGEST_KEY set",
        )
    if not secrets.compare_digest(creds.credentials, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------- App factory ----------


def create_app(
    config: Config,
    config_path: str | os.PathLike[str] | None = None,
) -> FastAPI:
    """Build the FastAPI app. The data_root and api_key are taken from the
    server's environment (MEMLOOM_INGEST_KEY)."""
    from pathlib import Path

    from .admin.state import AdminState

    app = FastAPI(
        title="memloom",
        version=__version__,
        description="memloom HTTP ingest + admin dashboard + MCP.",
    )
    store = RawStore(config.pipeline.data_root)
    privacy = (
        PrivacyFilter(
            patterns=config.privacy.strip_patterns,
            replacement=config.privacy.redact_replacement,
        )
        if config.privacy.enabled else None
    )
    denoiser = Denoiser() if getattr(config, "denoise", None) and config.denoise.enabled else None
    deduper = Deduper()
    admin_state = AdminState(
        config=config,
        store=store,
        config_path=Path(config_path).expanduser() if config_path else None,
    )
    if not getattr(config, "_skip_embed_for_test", False):
        admin_state.rebuild_embedder()
        if (
            getattr(config, "embed", None)
            and config.embed.enabled
            and admin_state.embedder is None
        ):
            log.warning("embedder init failed or unavailable")
    embedder = admin_state.embedder

    @app.post("/ingest", response_model=IngestResponse, status_code=200)
    def ingest(
        payload: IngestRequest,
        _auth: None = Depends(_verify_bearer),
    ) -> IngestResponse:
        accepted = 0
        skipped = 0
        errors: list[str] = []

        for i, r in enumerate(payload.records):
            try:
                rec = MemoryRecord.from_dict(r)
            except (ValidationError, TypeError, KeyError) as e:
                errors.append(f"record {i}: invalid format: {e}")
                continue

            # 1) Privacy filter
            if privacy is not None:
                rec, _changed = privacy.filter_record(rec)
                if not rec.content:
                    errors.append(f"record {i} ({rec.id}): empty after privacy filter")
                    continue

            # 1b) Denoise
            if denoiser is not None:
                rec, _changed = denoiser.denoise_record(rec)

            # 2) Tag
            rec = tag_record(rec)

            # 3) Cross-run dedup on id (record.id is derived from source+source_key)
            if store.has(rec.id):
                skipped += 1
                continue

            # 4) In-run content dedup (rare since cross-run usually catches first)
            if not deduper.is_new(rec):
                skipped += 1
                continue

            # 5) Upsert
            try:
                store.upsert(rec)
                accepted += 1
            except Exception as e:
                errors.append(f"record {i} ({rec.id}): upsert failed: {e}")
                continue

            # 6) Embed (best-effort, don't fail the request)
            if embedder is not None and rec.content and not payload.skip_embed:
                try:
                    vec = embedder.embed_one(rec.content)
                    if vec is not None:
                        store.upsert_vector(rec.id, vec)
                except Exception as e:
                    log.warning("embed failed for %s: %s", rec.id, e)

        return IngestResponse(accepted=accepted, skipped=skipped, errors=errors)

    @app.get("/health", response_model=HealthResponse)
    def health() -> HealthResponse:
        s = store.stats()
        return HealthResponse(status="ok", records=s["total"], vectors=s.get("vectors", 0))

    @app.get("/stats")
    def stats() -> dict:
        return store.stats()

    # ── Search endpoints ──────────────────────────────────────────────────

    from pydantic import BaseModel as PydanticBaseModel

    class SearchResult(PydanticBaseModel):
        id: str
        source: str
        source_key: str
        role: str
        content: str
        score: float
        agent: str = ""

    @app.get("/api/search", dependencies=[Depends(_verify_bearer)])
    def search(q: str = "", source: str = "", limit: int = 20, hybrid: bool = True):
        """Full-text or hybrid search across all collected records."""
        if not q.strip():
            return []

        src = source if source else None

        if hybrid and embedder is not None:
            try:
                query_vec = embedder.embed_one(q.strip())
                results = store.hybrid_search(query=q.strip(), query_vec=query_vec, source=src, limit=limit)
            except Exception:
                results = store.search(query=q.strip(), source=src, limit=limit)
        else:
            results = store.search(query=q.strip(), source=src, limit=limit)

        return [
            {
                "id": r.get("id", ""),
                "source": r.get("source", ""),
                "source_key": r.get("source_key", r.get("json_path", "")),
                "role": r.get("role", ""),
                "content": r.get("snippet", r.get("snip", ""))[:800],
                "score": float(r.get("rrf", r.get("rank", 0))),
                "agent": r.get("agent", ""),
                "path": r.get("json_path", ""),
            }
            for r in results
        ]

    # ── MCP endpoint (Model Context Protocol — JSON-RPC 2.0) ──────────────
    # Minimal implementation supporting tools/list and tools/call.
    # Tools are agents that can search memloom's hybrid store.

    MCP_TOOLS = [
        {
            "name": "search_memory",
            "description": "Search the user's agent memory database (FTS5 + vector hybrid). "
                           "Returns the top-matching conversation snippets. Use this whenever "
                           "the user asks about past work, servers, projects, decisions, or "
                           "any topic that might have been discussed before.",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query. Use specific terms like '188.245', 'pbeta.me', 'hetzner server', etc.",
                    },
                    "source": {
                        "type": "string",
                        "description": "Optional source filter: opencode, codex, hermes, kilocode, qoder, antigravity, etc.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default 10)",
                        "default": 10,
                    },
                },
                "required": ["query"],
            },
        },
    ]

    @app.post("/mcp", dependencies=[Depends(_verify_bearer)])
    def mcp_endpoint(req: dict):
        method = req.get("method", "")
        req_id = req.get("id")
        result = None
        error = None

        if method == "initialize":
            result = {
                "protocolVersion": "2024-11-05",
                "serverInfo": {"name": "memloom", "version": __version__},
                "capabilities": {"tools": {}},
            }
        elif method == "tools/list":
            result = {"tools": MCP_TOOLS}
        elif method == "tools/call":
            params = req.get("params", {})
            name = params.get("name", "")
            args = params.get("arguments", {})
            if name == "search_memory":
                # Reuse the /api/search logic inline
                q = args.get("query", "").strip()
                if not q:
                    result = {"content": [{"type": "text", "text": "Error: query is required"}]}
                else:
                    src = args.get("source") or None
                    limit = int(args.get("limit", 10))
                    if embedder is not None:
                        try:
                            query_vec = embedder.embed_one(q)
                            results = store.hybrid_search(query=q, query_vec=query_vec, source=src, limit=limit)
                        except Exception:
                            results = store.search(query=q, source=src, limit=limit)
                    else:
                        results = store.search(query=q, source=src, limit=limit)
                    lines = []
                    for r in results:
                        snip = r.get("snippet", r.get("snip", ""))
                        lines.append(
                            f"[{r.get('source','?')}] {snip}\n"
                            f"  (id={r.get('id','')}, score={r.get('rrf', r.get('rank', 0)):.4f})"
                        )
                    text = "\n\n".join(lines) if lines else "(no results)"
                    result = {"content": [{"type": "text", "text": text}]}
            else:
                error = {"code": -32601, "message": f"Unknown tool: {name}"}
        else:
            error = {"code": -32601, "message": f"Method not found: {method}"}

        response = {"jsonrpc": "2.0", "id": req_id}
        if error:
            response["error"] = error
        else:
            response["result"] = result
        return response

    # ── Admin API (dashboard) ─────────────────────────────────────────────
    from .admin.router import build_admin_router
    from .admin.static import mount_spa

    app.include_router(build_admin_router(admin_state))
    mount_spa(app)

    return app


def generate_key() -> str:
    """Return a fresh 32-byte URL-safe token, prefixed for clarity."""
    return "memloom_ingest_" + secrets.token_urlsafe(24)


__all__ = ["create_app", "generate_key", "IngestRequest", "IngestResponse", "HealthResponse"]