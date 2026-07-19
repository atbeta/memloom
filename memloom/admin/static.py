"""Serve the built dashboard SPA from memloom/admin/static."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).resolve().parent / "static"


def mount_spa(app: FastAPI) -> None:
    """Mount built assets and SPA fallback when index.html exists."""
    index = STATIC_DIR / "index.html"
    if not index.is_file():
        return

    assets_dir = STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="dashboard-assets")

    @app.get("/")
    def spa_index() -> FileResponse:
        return FileResponse(index)

    @app.get("/{full_path:path}")
    def spa_fallback(full_path: str) -> FileResponse:
        # Never shadow API / ingest routes (registered earlier).
        if full_path.startswith(("api/", "ingest", "health", "stats", "mcp", "docs", "openapi")):
            raise HTTPException(status_code=404, detail="not found")
        candidate = STATIC_DIR / full_path
        if candidate.is_file() and STATIC_DIR in candidate.resolve().parents:
            return FileResponse(candidate)
        return FileResponse(index)
