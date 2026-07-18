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
    uv run memloom serve --port 8765 --config ./memloom.yaml

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

from .config import Config, load_config
from .embed import EmbedConfig, Embedder
from .pipeline import Deduper, PrivacyFilter, tag_record
from .records import MemoryRecord
from .runner import Runner
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


def create_app(config: Config) -> FastAPI:
    """Build the FastAPI app. The data_root and api_key are taken from the
    server's environment (MEMLOOM_INGEST_KEY)."""
    app = FastAPI(
        title="memloom-ingest",
        version="0.1.0",
        description="HTTP ingest endpoint for memloom. POST /ingest accepts records.",
    )
    store = RawStore(config.pipeline.data_root)
    privacy = (
        PrivacyFilter(
            patterns=config.privacy.strip_patterns,
            replacement=config.privacy.redact_replacement,
        )
        if config.privacy.enabled else None
    )
    deduper = Deduper()
    embedder: Embedder | None = None
    if (
        getattr(config, "embed", None)
        and config.embed.enabled
        and not getattr(config, "_skip_embed_for_test", False)
    ):
        try:
            embedder = Embedder(EmbedConfig(
                base_url=config.embed.base_url,
                api_key=config.embed.api_key,
                model=config.embed.model,
                dimension=config.embed.dimension,
                batch_size=config.embed.batch_size,
                timeout=config.embed.timeout,
                max_retries=config.embed.max_retries,
                enabled=True,
            ))
        except Exception as e:
            log.warning("embedder init failed: %s", e)

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

    return app


def generate_key() -> str:
    """Return a fresh 32-byte URL-safe token, prefixed for clarity."""
    return "memloom_ingest_" + secrets.token_urlsafe(24)


__all__ = ["create_app", "generate_key", "IngestRequest", "IngestResponse", "HealthResponse"]