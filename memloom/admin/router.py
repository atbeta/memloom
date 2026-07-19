"""Admin REST routes for the dashboard (Phase 1: read-only)."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..config import Config
from ..embed import Embedder
from ..store import RawStore
from .auth import verify_admin_bearer

log = logging.getLogger(__name__)


def build_admin_router(
    store: RawStore,
    config: Config,
    embedder: Embedder | None = None,
) -> APIRouter:
    router = APIRouter(
        prefix="/api/admin",
        tags=["admin"],
        dependencies=[Depends(verify_admin_bearer)],
    )

    @router.get("/overview")
    def overview(runs_limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
        stats = store.stats()
        return {
            "total": stats["total"],
            "by_source": stats["by_source"],
            "vectors": stats.get("vectors", 0),
            "runs": store.recent_runs(limit=runs_limit),
            "data_root": config.pipeline.data_root,
            "embed_enabled": bool(getattr(config, "embed", None) and config.embed.enabled),
            "agent_count": len(config.all_enabled_agents()),
            "host_count": len(config.hosts),
        }

    @router.get("/runs")
    def runs(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        return store.recent_runs(limit=limit)

    @router.get("/search")
    def search(
        q: str = "",
        source: str = "",
        limit: int = Query(20, ge=1, le=200),
        hybrid: bool = True,
    ) -> list[dict[str, Any]]:
        if not q.strip():
            return []

        src = source if source else None
        results: list[dict[str, Any]]

        if hybrid and embedder is not None:
            try:
                query_vec = embedder.embed_one(q.strip())
                results = store.hybrid_search(
                    query=q.strip(), query_vec=query_vec, source=src, limit=limit,
                )
            except Exception:
                log.exception("admin hybrid search failed; falling back to FTS5")
                results = store.search(query=q.strip(), source=src, limit=limit)
        else:
            results = store.search(query=q.strip(), source=src, limit=limit)

        return [
            {
                "id": r.get("id", ""),
                "source": r.get("source", ""),
                "source_key": r.get("source_key", ""),
                "role": r.get("role", ""),
                "content": (r.get("snippet") or r.get("snip") or "")[:800],
                "score": float(r.get("rrf_score", r.get("rrf", r.get("rank", 0))) or 0),
                "agent": r.get("agent", "") or "",
                "project": r.get("project"),
                "captured_at": r.get("captured_at"),
                "path": r.get("json_path", ""),
            }
            for r in results
        ]

    @router.get("/records/{record_id}")
    def get_record(record_id: str) -> dict[str, Any]:
        got = store.get_record(record_id)
        if got is None:
            raise HTTPException(status_code=404, detail=f"record not found: {record_id}")
        return got

    return router
