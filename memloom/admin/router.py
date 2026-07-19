"""Admin REST routes for the dashboard."""
from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..ops import embed_backfill, run_summaries_to_dicts
from ..quarantine import list_quarantined, move_to_quarantine, restore_from_quarantine
from ..runner import Runner
from .auth import verify_admin_bearer
from .settings import apply_settings_patch, save_config_yaml, settings_public_view
from .state import AdminState

log = logging.getLogger(__name__)


class CollectBody(BaseModel):
    agents: list[str] | None = None
    hosts: list[str] | None = None


class EmbedBody(BaseModel):
    source: str | None = None
    limit: int = Field(0, ge=0)
    force: bool = False
    batch_size: int = Field(32, ge=1, le=256)


class QuarantineIdsBody(BaseModel):
    record_ids: list[str] = Field(..., min_length=1)
    reason: str = "manual"


def build_admin_router(state: AdminState) -> APIRouter:
    router = APIRouter(
        prefix="/api/admin",
        tags=["admin"],
        dependencies=[Depends(verify_admin_bearer)],
    )

    @router.get("/overview")
    def overview(runs_limit: int = Query(20, ge=1, le=200)) -> dict[str, Any]:
        cfg = state.config
        stats = state.store.stats()
        return {
            "total": stats["total"],
            "by_source": stats["by_source"],
            "vectors": stats.get("vectors", 0),
            "runs": state.store.recent_runs(limit=runs_limit),
            "data_root": cfg.pipeline.data_root,
            "embed_enabled": bool(getattr(cfg, "embed", None) and cfg.embed.enabled),
            "agent_count": len(cfg.all_enabled_agents()),
            "host_count": len(cfg.hosts),
        }

    @router.get("/runs")
    def runs(limit: int = Query(50, ge=1, le=500)) -> list[dict[str, Any]]:
        return state.store.recent_runs(limit=limit)

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

        if hybrid and state.embedder is not None:
            try:
                query_vec = state.embedder.embed_one(q.strip())
                results = state.store.hybrid_search(
                    query=q.strip(), query_vec=query_vec, source=src, limit=limit,
                )
            except Exception:
                log.exception("admin hybrid search failed; falling back to FTS5")
                results = state.store.search(query=q.strip(), source=src, limit=limit)
        else:
            results = state.store.search(query=q.strip(), source=src, limit=limit)

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
        got = state.store.get_record(record_id)
        if got is None:
            raise HTTPException(status_code=404, detail=f"record not found: {record_id}")
        return got

    # ── Settings ──────────────────────────────────────────────────────────

    @router.get("/settings")
    def get_settings() -> dict[str, Any]:
        return settings_public_view(state.config, state.config_path)

    @router.patch("/settings")
    def patch_settings(patch: dict[str, Any]) -> dict[str, Any]:
        try:
            new_cfg, warnings = apply_settings_patch(state.config, patch)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e)) from e

        if state.config_path is None:
            raise HTTPException(
                status_code=400,
                detail="no config file path — start serve with --config to enable writes",
            )
        try:
            save_config_yaml(new_cfg, state.config_path)
        except OSError as e:
            raise HTTPException(status_code=500, detail=f"failed to write config: {e}") from e

        state.config = new_cfg
        state.rebuild_embedder()
        view = settings_public_view(state.config, state.config_path)
        view["warnings"] = warnings
        return view

    # ── Actions ───────────────────────────────────────────────────────────

    @router.post("/actions/collect")
    def action_collect(body: CollectBody | None = None) -> dict[str, Any]:
        body = body or CollectBody()
        runner = Runner(state.config, store=state.store)
        try:
            summaries = runner.collect_once(
                only_agents=body.agents,
                only_hosts=body.hosts,
            )
        except Exception as e:
            log.exception("admin collect failed")
            raise HTTPException(status_code=500, detail=str(e)) from e
        return {"ok": True, "runs": run_summaries_to_dicts(summaries)}

    @router.post("/actions/embed")
    def action_embed(body: EmbedBody | None = None) -> dict[str, Any]:
        body = body or EmbedBody()
        emb = getattr(state.config, "embed", None)
        if emb is None or not emb.enabled:
            raise HTTPException(status_code=400, detail="embed.enabled=true required in config")
        if state.embedder is None:
            state.rebuild_embedder()
        if state.embedder is None:
            raise HTTPException(status_code=500, detail="embedder unavailable")
        if not state.embedder.health_check():
            raise HTTPException(
                status_code=502,
                detail=f"embedder unreachable at {emb.base_url}",
            )
        result = embed_backfill(
            state.store,
            state.embedder,
            source=body.source,
            limit=body.limit,
            force=body.force,
            batch_size=body.batch_size,
        )
        return {"ok": True, **result}

    # ── Quarantine ────────────────────────────────────────────────────────

    @router.get("/quarantine")
    def quarantine_list() -> list[dict[str, Any]]:
        return list_quarantined(state.store)

    @router.post("/quarantine/add")
    def quarantine_add(body: QuarantineIdsBody) -> dict[str, Any]:
        result = move_to_quarantine(state.store, body.record_ids, reason=body.reason)
        return {
            "moved": result.moved,
            "skipped": result.skipped,
            "not_found": result.not_found,
            "errors": result.errors,
        }

    @router.post("/quarantine/restore")
    def quarantine_restore(body: QuarantineIdsBody) -> dict[str, Any]:
        return restore_from_quarantine(state.store, body.record_ids)

    return router
